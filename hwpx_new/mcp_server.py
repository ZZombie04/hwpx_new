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
SERVER_VERSION = '2.3.0'
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
    '## 작업 고르기(먼저)\n'
    '- 서식을 그대로 살린 새 문서 → 아래 1~5 (hwpx_analyze → hwpx_build)\n'
    '- 정돈된 계획서·안내문(Ⅰ→■→❍→-) → hwpx_compose(명세 JSON)\n'
    '- 공문(내부 기안문·겉공문·시행문) → hwpx_gongmun(명세 JSON, 기관 공문 서식 필요)\n'
    '- 사용자가 한글에서 손본 파일 고치기 → hwpx_patch(ops JSON) / 글자만 바꾸기 → hwpx_replace\n'
    '- 점검 → hwpx_qa("오류 0" 까지) + hwpx_preview(모든 쪽)\n'
    '- 사진 때문에 문서가 무거움 → hwpx_shrink(보이는 크기 × 200dpi 로 그림만 줄임, 새 파일)\n'
    '- **장편 보고서**(연구학교 결과보고서·연구보고서·논문형, 20~60쪽, 서식 파일 없이) → hwpx_report_guide → '
    'hwpx_report_example(폴더) → 그 원고를 요청에 맞게 고쳐 쓰기(숫자는 @stats 계산 명령, 도표는 @chart 자료) → '
    'hwpx_report_build → hwpx_preview 로 모든 쪽 확인 → 오류 0 까지 원고 수정\n'
    '명세 문법: hwpx_format_guide. 사실은 입력에서만, 없는 값은 ○○ 로 비우고 보고.\n\n'
    '## hwpx_new 사용 순서(서식 재현)\n'
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


def _spec_arg(spec):
    """명세 인자: dict, JSON 문자열, 또는 JSON 파일 경로."""
    if isinstance(spec, (dict, list)):
        return spec
    return spec


@tool('공문(기안문·시행문)을 만든다: 기관 공문 서식(머리 표·결재란이 든 HWPX) + 내용 명세(JSON) → HWPX. '
      '본문 번호 체계(1.→가.→1)→가))·표·QR·붙임/끝·발신 명의·수신자 줄은 도구가 정한다. 명세 문법은 hwpx_format_guide 의 "공문 명세".',
      spec=('string', '공문 명세 JSON(문자열 또는 파일 경로). template·receiver·title·body·attachments·sender·receivers·approval'),
      output=('string', '결과 HWPX 경로'), check=('boolean', 'PDF 로 바꿔 조판 점검까지(기본 true)', False))
def hwpx_gongmun(spec, output, check=True):
    from .gongmun import build
    build(_spec_arg(spec), output)
    return output + ('\n' + _qa_text(output) if check else '')


@tool('정돈 조판(계획서·안내문, Ⅰ→■→❍→- 체계): 서식 + 명세(JSON) → HWPX. 파이썬 없이 Composer 를 쓴다.',
      spec=('string', '조판 명세 JSON(문자열 또는 파일 경로). template·heading_block·cover·blocks·title'),
      output=('string', '결과 HWPX 경로'), check=('boolean', 'PDF 로 바꿔 조판 점검까지(기본 true)', False))
def hwpx_compose(spec, output, check=True):
    from .spec import build
    build(_spec_arg(spec), output)
    return output + ('\n' + _qa_text(output) if check else '')


@tool('사용자가 한글에서 손본 HWPX 를 손본 그대로 두고, 글로 찾은 곳만 고친다(replace_text·replace_block·insert_after·'
      'insert_before·delete_block·page_break). 원본은 덮어쓰지 말고 output 을 새 경로로.',
      src=('string', '원본 HWPX'), ops=('string', '고칠 내용 JSON 배열(문자열 또는 파일 경로)'),
      output=('string', '결과 HWPX 경로'), style=('string', "새로 넣는 문단 모양: 'plan'(계획서) 또는 'gongmun'(공문)", False),
      check=('boolean', 'PDF 로 바꿔 조판 점검까지(기본 true)', False))
def hwpx_patch(src, ops, output, style='plan', check=True):
    from .patch import patch
    rep = patch(src, ops, output, style=style)
    return '\n'.join(rep + [output]) + ('\n' + _qa_text(output) if check else '')


@tool('이름·날짜 같은 문자열만 바꾼다(나머지 내용·서식은 바이트 그대로). pairs 는 [["옛 글","새 글"], …].',
      src=('string', '원본 HWPX'), output=('string', '결과 HWPX'), pairs=('array', '[["옛 글","새 글"], …]'))
def hwpx_replace(src, output, pairs):
    from .patch import replace_text_zip
    hits = replace_text_zip(src, output, [tuple(p) for p in pairs])
    return '\n'.join(f'"{k}": 본문 {n}곳' for k, n in hits.items()) + f'\n{output}'


@tool('HWPX 안 그림을 표시 크기에 맞춰 줄여 문서 용량을 줄인다(사진은 JPEG·도표는 팔레트 PNG, 글·서식은 그대로).',
      src=('string', '원본 HWPX'), output=('string', '결과 HWPX'), dpi=('integer', '표시 크기 기준 해상도(기본 200)', False))
def hwpx_shrink(src, output, dpi=200):
    from .images import shrink_hwpx
    rep, (b, f) = shrink_hwpx(src, output, dpi=int(dpi))
    return '\n'.join(f'{n}: {x}KB → {y}KB' for n, x, y in rep) + f'\n문서 {b}KB → {f}KB: {output}'


def _qa_text(path):
    import io
    import contextlib
    from . import layout_qa
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        layout_qa.main([path, '--strict'])
    return buf.getvalue().strip()


@tool('조판 점검: HWPX 또는 PDF 를 검사한다(글자색·단계 정렬·내어쓰기·여백·겹침·쪽 끝 소제목·빈 쪽·공문 결재란 위치). '
      '"오류 0" 이 될 때까지 고친 뒤 hwpx_preview 로 쪽 그림도 확인한다.', path=('string', 'HWPX 또는 PDF 경로'))
def hwpx_qa(path):
    return _qa_text(path)


@tool('장편 보고서(연구학교 결과보고서·연구보고서·논문형) 원고 문법과 좋은 보고서 규칙을 돌려준다. 보고서 원고를 쓰기 전에 먼저 본다.')
def hwpx_report_guide():
    from .report_cmd import guide_text
    return guide_text()


@tool('바로 빌드되는 완성 예시(원고 report.txt·자료 CSV·사진)를 folder 에 만들고 원고 전문을 돌려준다. 새 보고서는 이 원고를 고쳐 쓴다'
      '(이미 report.txt 가 있으면 덮어쓰지 않고 그 원고를 돌려줌).', folder=('string', '예시를 만들 폴더(없으면 만듦)'))
def hwpx_report_example(folder):
    from .report_cmd import init_example
    path = os.path.join(folder, 'report.txt')
    if os.path.exists(path):
        head = f'이미 원고가 있어 그대로 둡니다: {path}\n\n'
    else:
        files = init_example(folder)
        head = (f'예시를 만들었습니다: {os.path.abspath(folder)} ({len(files)}개 파일: report.txt, data.csv, students.csv, '
                f'ratings.csv, photos/)\n\n')
    return head + open(path, encoding='utf-8').read()


@tool('보고서 원고(report.txt 또는 원고 폴더) → HWPX + PDF. 표·그림 번호, 차례·표 차례 쪽수, 표 쪽 넘김, 통계(@stats)·도표(@chart)를 '
      '도구가 맞추고(PDF 로 확인하며 몇 번 반복, 1~3분) 점검 결과(오류·주의)를 돌려준다.',
      manuscript=('string', '원고 파일(report.txt) 또는 원고 폴더 경로'), output_dir=('string', '결과 폴더'),
      name=('string', '파일 이름(생략하면 제목)', False), engine=('string', 'hancom|libreoffice|html (생략 시 자동)', False))
def hwpx_report_build(manuscript, output_dir, name='', engine=''):
    from .report import build_report, summarize
    res = build_report(manuscript, output_dir, name=name or None, engine=engine or None,
                       progress=lambda k, n, m: _progress(k, n, m))
    return summarize(res)


@tool('보고서 원고 점검: 풀지 못한 {{토큰}}·{표:키} 참조, 인용↔참고문헌, 날짜 요일, 근거보다 큰 말, 검정 없는 "유의", '
      '(pdf_path 를 주면) 쪽 수 상한·장 중간의 큰 빈칸.', manuscript=('string', '원고 파일 또는 폴더'),
      pdf_path=('string', '빌드한 PDF(선택)', False))
def hwpx_report_check(manuscript, pdf_path=''):
    from .report import read_manuscript
    from .report_check import check
    iss = check(read_manuscript(manuscript), pdf_path or None)
    errs = sum(1 for x in iss if x[0] == '오류')
    return '\n'.join(f'[{lv}] {m}' for lv, m in iss) + f'\n결과: 오류 {errs}, 주의 {sum(1 for x in iss if x[0] == "주의")}'


@tool('보고서용 통계(외부 패키지 없이): paired(짝지은 t·d·CI)·welch(독립 두 집단·g)·alpha(α)·kappa(가중 κ)·corr(r)·desc(기술 통계)·'
      'freq(비율). 한 줄 요약과 원고 토큰(@set)을 돌려준다. 숫자를 직접 계산하지 말고 이 도구를 쓴다. 원고에는 같은 명령을 '
      '"@stats …" 줄로 써 두면 조판 때 자동 계산된다.',
      command=('string', "예: 'paired 자료.csv --pre 사전 --post 사후 --prefix ref' (--where 경력=초임 으로 일부 행)"),
      base_dir=('string', '자료 파일의 상대 경로 기준 폴더(보통 원고 폴더)', False))
def hwpx_stats(command, base_dir=''):
    from .stats import run_line
    toks, summary = run_line(command, base_dir or None)
    return summary + '\n\n' + '\n'.join(f'@set {k} = {v}' for k, v in toks.items())


@tool('보고서와 같은 디자인의 도표 PNG 를 그린다(bar·hbar·group·dumbbell·stack·effect·hist·scatter·line·timeline·steps·cycle). '
      '보고서 원고 안에서는 @chart 로 쓰면 되고, 이 도구는 다른 문서에 넣을 도표를 따로 만들 때 쓴다.',
      spec=('string', 'JSON 문자열 또는 파일 경로. 예: {"type":"bar","label":"월별 건수","rows":[["4월",12],["5월",18]]}'),
      output=('string', '저장할 PNG 경로'), accent=('string', '강조색 #RRGGBB(선택)', False))
def hwpx_chart(spec, output, accent=''):
    from .charts import render
    path = render(json.dumps(spec, ensure_ascii=False) if isinstance(spec, (dict, list)) else spec, output, accent or None)
    with open(path, 'rb') as f:
        return [path, Image(f.read(), 'png')]


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
