# -*- coding: utf-8 -*-
"""MCP 서버(stdio). 외부 패키지 없이 표준 라이브러리만으로 구현해 어떤 AI(Claude Desktop/Code, Codex, Gemini CLI,
Cursor, Antigravity …)에서도 설치 문제 없이 연결된다.

프로토콜: 줄 단위 JSON-RPC 2.0 (initialize / tools/list / tools/call / ping).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
import traceback

GUIDE = os.path.join(os.path.dirname(__file__), 'FORMAT.md')
SERVER_NAME = 'hwpx_new'
SERVER_VERSION = '2.0.0'
SUPPORTED = ('2025-06-18', '2025-03-26', '2024-11-05', '2024-10-07')

TOOLS = {}
_LOCK = threading.Lock()
_CTX = {'out': None, 'token': None}


def _write(obj):
    out = _CTX['out'] or sys.stdout
    with _LOCK:
        out.write(json.dumps(obj, ensure_ascii=False) + '\n')
        out.flush()


def _progress(n=0, total=None, msg=''):
    """클라이언트가 progressToken 을 줬을 때만 진행 알림을 보낸다(오래 걸리는 빌드가 시간 초과로 끊기지 않도록)."""
    tok = _CTX.get('token')
    if tok is None:
        return
    p = {'progressToken': tok, 'progress': n}
    if total is not None:
        p['total'] = total
    if msg:
        p['message'] = msg
    _write({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': p})


def tool(description, **props):
    """도구 등록 데코레이터. props: 인자 이름 → (타입, 설명, 필수 여부, 기본값)"""
    def deco(fn):
        schema = {'type': 'object', 'properties': {}, 'required': []}
        for name, spec in props.items():
            typ, desc = spec[0], spec[1]
            req = spec[2] if len(spec) > 2 else True
            schema['properties'][name] = {'type': typ, 'description': desc}
            if req:
                schema['required'].append(name)
        TOOLS[fn.__name__] = {'fn': fn, 'description': description, 'schema': schema}
        return fn
    return deco


class Image:
    """도구가 이미지를 돌려줄 때 쓰는 포장."""

    def __init__(self, data: bytes, fmt: str = 'png'):
        self.data, self.fmt = data, fmt


START_HERE = (
    '## hwpx_new 사용 순서\n'
    '1. hwpx_analyze(template_path): 사용자가 준 HWPX 서식을 분석한다(서식 종류 목록·블록 목록·표지 칸). 이어서 나오는 "뼈대 Markdown"이\n'
    '   서식을 그대로 다시 만들 수 있는 문서다.\n'
    '2. 그 뼈대 Markdown 을 사용자의 요청(예: 계획서 → 결과보고서)에 맞게 고쳐 쓴다. `{B2}` 같은 서식 종류 표시·`@clone N` 줄은 지우지 말고,\n'
    '   비슷한 줄을 더 쓸 때는 같은 표시를 복사한다. 문법은 hwpx_format_guide.\n'
    '   - 사용자가 주지 않은 사실을 지어 넣었다면 최종 답변에서 반드시 밝힌다.\n'
    '3. hwpx_build(template_path, content, output_dir): HWPX + PDF 를 한 번에 만든다(조판 자동 점검·보정, 서식 재현 점검 포함).\n'
    '   - 사진: hwpx_photos(폴더) → hwpx_photo_sheet(폴더)로 사진을 보고 `![캡션](경로)` / `:::photos` 로 넣는다.\n'
    '4. hwpx_preview(pdf_path, page): 결과 PDF 를 눈으로 확인한다. 어색하면 내용을 고쳐 3번을 다시 호출한다.\n'
    '5. 사용자에게 HWPX·PDF 경로와 지어 넣은 내용(있다면)을 알린다.\n'
    '※ .hwp(옛 형식)는 hwpx_convert_hwp 로 바꾼다(Windows + 한글). 안 되면 한글에서 HWPX 로 다시 저장.')


@tool('가장 먼저 호출. 이 도구 모음의 사용 순서와 규칙을 알려 준다.')
def hwpx_start_here():
    return START_HERE


@tool('PDF 변환 엔진(한글/LibreOffice/내장)과 한글 자동화 상태를 점검한다.')
def hwpx_doctor():
    from .pdf import available_engines
    e = available_engines()
    return (f'한글(Hancom): {e["hancom"]}\nLibreOffice: {e["libreoffice"]}\n내장 렌더러: 가능 (브라우저 {e["browser"]})\n'
            + ('한글이 있어 실제와 동일한 PDF 가 만들어진다. 한글이 "파일 접근 허용" 창을 띄우면 이 도구가 자동으로 누른다'
               '(화면보호기·잠금 상태에서는 눌리지 않으니 화면을 켠 채 사용).' if e['hancom'] else
               '한글이 없어 근사 PDF 가 만들어질 수 있다(쪽 배치가 실제와 조금 다를 수 있음).'))


@tool('내용 작성 문법(Markdown 확장 / JSON 블록)을 돌려준다.')
def hwpx_format_guide():
    return open(GUIDE, encoding='utf-8').read()


@tool('HWPX 서식을 분석해 문서 구조(표지·소제목·표·박스·글머리·서식 종류)와, 그 서식을 그대로 다시 만드는 뼈대 Markdown 을 돌려준다.',
      template_path=('string', '서식 HWPX 파일 경로'))
def hwpx_analyze(template_path):
    from .analyze import analyze, blueprint_markdown, scaffold_markdown
    bp = analyze(template_path)
    return blueprint_markdown(bp) + '\n\n---\n## 뼈대 Markdown(이 구조와 표시를 살려 새 목적에 맞게 고쳐 쓰세요)\n\n```markdown\n' + \
        scaffold_markdown(bp) + '```\n'


@tool('HWPX 문서의 본문을 Markdown 으로 읽는다(참고 자료·기존 문서 확인용).', path=('string', 'HWPX 파일 경로'))
def hwpx_read(path):
    from .analyze import dump_document
    return dump_document(path)


@tool('서식 + 내용으로 HWPX 와 PDF 를 만든다(조판 자동 점검·보정, 서식 재현 점검 포함). content 는 Markdown(확장)/JSON 문자열 또는 그 파일 경로.',
      template_path=('string', '서식 HWPX 파일 경로'),
      content=('string', 'Markdown(확장) 또는 JSON 문자열, 혹은 그 내용이 담긴 파일 경로'),
      output_dir=('string', '결과를 저장할 폴더'),
      name=('string', '파일 이름(생략하면 제목)', False),
      engine=('string', 'hancom|libreoffice|html (생략 시 자동)', False))
def hwpx_build(template_path, content, output_dir, name='', engine=''):
    from .pipeline import make_report, summarize
    res = make_report(template_path, content, output_dir, name=name or None, engine=engine or None, progress=_progress)
    return summarize(res)


@tool('옛 .hwp 파일을 .hwpx 로 변환한다(Windows + 한글 필요). 결과 경로를 돌려준다.', hwp_path=('string', '.hwp 파일 경로'))
def hwpx_convert_hwp(hwp_path):
    from .pdf import hwp_to_hwpx
    out = os.path.splitext(hwp_path)[0] + '.hwpx'
    ok, msg = hwp_to_hwpx(hwp_path, out)
    return msg if ok else '변환 실패: ' + msg


@tool('사진 폴더(또는 사진 파일)를 살펴본다: 촬영 시각 순 목록과 번호가 붙은 한눈에 보기 이미지 경로를 돌려준다.',
      folder=('string', '사진 폴더 또는 파일 경로'))
def hwpx_photos(folder):
    from .photos import describe_folder
    text, _sheet = describe_folder(folder)
    return text


@tool("hwpx_photos 가 만든 '번호 붙은 사진 한눈에 보기' 이미지를 돌려준다(사진 내용을 파악할 때 사용).", folder=('string', '사진 폴더 경로'))
def hwpx_photo_sheet(folder):
    from .photos import describe_folder
    _text, sheet = describe_folder(folder)
    with open(sheet, 'rb') as f:
        return Image(f.read(), 'png')


@tool('PDF 의 한 쪽을 이미지로 돌려준다(결과를 눈으로 확인할 때 사용).',
      pdf_path=('string', 'PDF 파일 경로'), page=('integer', '쪽 번호(1부터)', False), dpi=('integer', '해상도(기본 80)', False))
def hwpx_preview(pdf_path, page=1, dpi=80):
    import pymupdf
    d = pymupdf.open(pdf_path)
    pix = d[max(0, min(int(page), len(d)) - 1)].get_pixmap(dpi=int(dpi))
    return Image(pix.tobytes('png'), 'png')


# ---------------------------------------------------------------- JSON-RPC
def _content(res):
    if isinstance(res, Image):
        return [{'type': 'image', 'data': base64.b64encode(res.data).decode('ascii'), 'mimeType': 'image/' + res.fmt}]
    if isinstance(res, (list, tuple)):
        out = []
        for r in res:
            out += _content(r)
        return out
    return [{'type': 'text', 'text': '' if res is None else str(res)}]


def handle(msg):
    """요청 하나 처리 → 응답 dict (알림이면 None)."""
    method = msg.get('method')
    mid = msg.get('id')
    params = msg.get('params') or {}
    if mid is None:                      # 알림(notifications/initialized 등)은 응답하지 않는다
        return None

    def ok(result):
        return {'jsonrpc': '2.0', 'id': mid, 'result': result}

    def err(code, text):
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': text}}

    if method == 'initialize':
        ver = params.get('protocolVersion')
        return ok({'protocolVersion': ver if ver in SUPPORTED else SUPPORTED[0],
                   'capabilities': {'tools': {'listChanged': False}},
                   'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
                   'instructions': START_HERE})
    if method == 'ping':
        return ok({})
    if method == 'tools/list':
        return ok({'tools': [{'name': n, 'description': t['description'], 'inputSchema': t['schema']}
                             for n, t in TOOLS.items()]})
    if method == 'tools/call':
        name = params.get('name')
        if name not in TOOLS:
            return err(-32602, f'알 수 없는 도구: {name}')
        args = params.get('arguments') or {}
        _CTX['token'] = (params.get('_meta') or {}).get('progressToken')
        stop = threading.Event()

        def beat():
            t0 = time.time()
            while not stop.wait(8.0):
                _progress(int(time.time() - t0), None, '작업 중… (한글 변환은 1~2분 걸릴 수 있습니다)')
        if _CTX['token'] is not None:
            threading.Thread(target=beat, daemon=True).start()
        try:
            res = TOOLS[name]['fn'](**args)
            return ok({'content': _content(res), 'isError': False})
        except TypeError as e:
            return ok({'content': [{'type': 'text', 'text': f'인자 오류: {e}'}], 'isError': True})
        except Exception as e:  # noqa
            return ok({'content': [{'type': 'text', 'text': f'오류: {e}'}], 'isError': True})
        finally:
            stop.set()
            _CTX['token'] = None
    if method in ('resources/list', 'prompts/list'):
        return ok({'resources' if method == 'resources/list' else 'prompts': []})
    return err(-32601, f'지원하지 않는 메서드: {method}')


def main():
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:  # noqa
            pass
    out = sys.stdout
    _CTX['out'] = out
    sys.stdout = sys.stderr            # 도구 안의 print 가 프로토콜 출력을 깨뜨리지 않도록
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            resp = handle(msg)
        except Exception:  # noqa
            traceback.print_exc(file=sys.stderr)
            resp = {'jsonrpc': '2.0', 'id': msg.get('id'), 'error': {'code': -32603, 'message': '내부 오류'}}
        if resp is not None:
            _write(resp)


if __name__ == '__main__':
    main()
