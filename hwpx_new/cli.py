# -*- coding: utf-8 -*-
"""명령줄 도구: hwpx-new (또는 python -m hwpx_new)"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(__file__)

PROMPT_TMPL = """너는 한글(HWPX) 문서 작성 도우미다. 아래 [서식 분석]은 사용자가 가진 서식 파일을 분석한 결과이고, [뼈대 Markdown]은
이 서식을 그대로 다시 만들어 내는 문서다. [요청]에 맞게 **글과 구조만** 고쳐 써서 **뼈대 Markdown 과 같은 문법**으로만 출력하라
(설명·머리말 없이 Markdown 본문만, 코드블록으로 감싸도 됨). 뼈대에 있는 `{B2}` 같은 서식 종류 표시, `:::cover` 칸 수, `@clone`·`@like`·json 블록은 그대로 둔다.

규칙
- 사용자가 주지 않은 사실(숫자·인명·날짜)을 지어 넣었다면, Markdown 맨 끝에 `<!-- 지어낸 내용: ... -->` 주석으로 목록을 남겨라.
- 서식의 문체(개조식 ~함/~임, 또는 ~합니다)와 번호 체계(Ⅰ. / 1. / 가.)를 그대로 쓴다.
- 날짜에 요일을 쓰면 실제 요일과 맞아야 한다.
- 서식 원문의 기관명·날짜가 남지 않게 모두 바꾼다.

[요청]
{request}

[서식 분석]
{analysis}

[뼈대 Markdown — 이 구조를 고쳐 쓴다]
```markdown
{scaffold}```

[내용 형식]
{fmt}
"""


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:  # noqa
            pass


def build_parser():
    ap = argparse.ArgumentParser(prog='hwpx-new',
                                 description='한글(HWPX) 서식을 분석해 같은 서식의 새 문서(HWPX+PDF)를 만듭니다.')
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('doctor', help='환경 점검(한글·PDF 엔진·자동 승인 등)')
    p.add_argument('--hancom', action='store_true', help='한글로 실제 PDF 변환을 한 번 해 보고 승인 창 자동 처리까지 점검')
    sub.add_parser('format', help='내용 작성 형식 안내 출력')
    sub.add_parser('instructions', help='AI 작업 지침(AGENTS.md) 출력 — 채팅형 AI 에 붙여 넣을 때')

    p = sub.add_parser('analyze', help='서식 분석 결과 출력(서식 종류·블록·뼈대 Markdown)')
    p.add_argument('template')
    p.add_argument('--json', action='store_true')

    for nm in ('skeleton', 'scaffold'):
        p = sub.add_parser(nm, help='서식을 그대로 다시 만드는 뼈대 Markdown 출력(AI 가 글만 고쳐 쓰는 출발점)')
        p.add_argument('template')
        p.add_argument('-o', '--out')

    p = sub.add_parser('selfcheck', help='서식을 다시 조립해 원본과 모양이 얼마나 같은지 점검(서식 재현도 %%)')
    p.add_argument('template')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('--pdf', action='store_true', help='원본·재조립본 PDF 도 만들어 저장')

    p = sub.add_parser('read', help='HWPX 본문을 Markdown 으로 읽기')
    p.add_argument('file')

    p = sub.add_parser('build', help='서식 + 내용 → HWPX + PDF (자동 조판 점검·보정 포함)')
    p.add_argument('template')
    p.add_argument('content', help='Markdown/JSON 파일 경로')
    p.add_argument('-o', '--out', default='output')
    p.add_argument('--name')
    p.add_argument('--engine', choices=['hancom', 'libreoffice', 'html'])
    p.add_argument('--no-autofix', action='store_true')
    p.add_argument('--no-preview', action='store_true')

    p = sub.add_parser('convert', help='.hwp → .hwpx 변환(Windows + 한글 필요)')
    p.add_argument('hwp')
    p.add_argument('-o', '--out')

    p = sub.add_parser('prompt', help='채팅형 AI(웹 ChatGPT 등)에 붙여 넣을 완성 프롬프트 출력')
    p.add_argument('template')
    p.add_argument('request', nargs='*', default=[], help='예: 이 계획서를 결과보고서로 바꿔줘. 이수 24명... (따옴표 없이 여러 단어도 가능)')

    p = sub.add_parser('setup', help='설치된 AI 프로그램(Claude·Codex·Gemini·Cursor…)에 MCP 자동 연결')
    p.add_argument('--yes', '-y', action='store_true', help='묻지 않고 모두 연결')
    p.add_argument('--dry-run', action='store_true', help='고치지 않고 무엇을 할지만 보여 줌')
    p.add_argument('--only', help='쉼표로 구분: claude-code,claude-desktop,codex,gemini,cursor,windsurf')
    p.add_argument('--home', help=argparse.SUPPRESS)
    p.add_argument('--skill', action='store_true', help='Claude Code 스킬(SKILL.md)도 설치')

    p = sub.add_parser('hancom-module', help='(선택) 한글 공식 자동화 보안 모듈 등록 — "파일 접근 허용" 창을 아예 없앰(보안 설정 변경)')
    p.add_argument('action', choices=['status', 'register', 'remove'])
    p.add_argument('--dll', help='한글 자동화 SDK 의 FilePathCheckerModule DLL 경로(register 때)')
    p.add_argument('--yes', '-y', action='store_true', help='확인 질문 없이 진행')

    sub.add_parser('mcp-config', help='MCP 설정 문구를 AI 프로그램별로 출력(직접 붙여 넣을 때)')

    p = sub.add_parser('photos', help='사진 폴더 살펴보기: 목록(촬영일시·크기) + 번호 붙은 한눈에 보기 이미지')
    p.add_argument('folder')
    p.add_argument('-o', '--out', help='한눈에 보기 이미지 저장 경로(기본: 폴더/_photo_sheet.png)')

    for nm, hp in (('report', '장편 보고서(연구학교 결과보고서·논문형): 원고(report.txt) → HWPX+PDF. init·check·guide·prompt'),
                   ('stats', '보고서용 통계: paired·welch·alpha·kappa·corr·desc·freq → 원고 토큰(@set)'),
                   ('chart', '보고서용 도표: 명세(JSON) → PNG(막대·묶음·효과 크기·산점도·흐름 등 12종)')):
        p = sub.add_parser(nm, help=hp, add_help=False)
        p.add_argument('rest', nargs=argparse.REMAINDER)

    p = sub.add_parser('qa', help='조판 점검: 글자색·단계 정렬·내어쓰기·글꼴·여백·겹침·쪽 끝 소제목·빈 쪽 + 문제 위치 표시 그림')
    p.add_argument('pdf')
    p.add_argument('-o', '--out', help='점검 결과 폴더(기본: PDF이름_점검)')
    p.add_argument('--skip', default='1', help='점검에서 뺄 쪽(쉼표, 기본: 표지 1쪽)')
    p.add_argument('--colors', default='#000000,#FFFFFF,#C00000', help='허용 글자색(쉼표)')

    p.add_argument('--strict', action='store_true', help='오류가 있으면 종료 코드 1')

    p = sub.add_parser('gongmun', help='공문(기안문·시행문) 만들기: 공문 서식 + 내용 명세(JSON) → HWPX')
    p.add_argument('spec', help='공문 명세 JSON 파일(examples/gongmun_spec.json 참고)')
    p.add_argument('-o', '--out', required=True, help='결과 HWPX 경로')
    p.add_argument('--check', action='store_true', help='PDF 로 바꿔 조판 점검(결재란 위치 포함)까지')

    p = sub.add_parser('compose', help='정돈 조판: 서식 + 명세(JSON) → 계획서·안내문 HWPX(Ⅰ→■→❍→- 체계)')
    p.add_argument('spec', help='조판 명세 JSON 파일(examples/compose_spec.json 참고)')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--check', action='store_true')

    p = sub.add_parser('patch', help='사용자가 손본 HWPX 를 손본 그대로 두고 글로 찾은 곳만 고치기(ops JSON)')
    p.add_argument('src')
    p.add_argument('ops', help='고칠 내용 JSON 파일(examples/patch_ops.json 참고)')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--style', choices=['plan', 'gongmun'], default='plan', help='새로 넣는 문단 모양(계획서/공문)')
    p.add_argument('--check', action='store_true')

    p = sub.add_parser('replace', help='이름·날짜 등 문자열만 바꾸기(나머지 파일 내용은 바이트 그대로)')
    p.add_argument('src')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--pair', action='append', required=True, help='"옛 글=>새 글" (여러 번 가능)')

    p = sub.add_parser('shrink', help='HWPX 안 그림을 표시 크기에 맞춰 줄여 문서 용량 줄이기(글·서식은 그대로)')
    p.add_argument('src')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--dpi', type=int, default=200, help='표시 크기 기준 해상도(기본 200, 인쇄해도 또렷함)')

    p = sub.add_parser('diff', help='두 HWPX 의 글 차이와 한글 저장 여부 확인(사용자가 손본 곳 찾기)')
    p.add_argument('a')
    p.add_argument('b')

    p = sub.add_parser('preview', help='PDF 한 쪽을 PNG 로 저장')
    p.add_argument('pdf')
    p.add_argument('--page', type=int, default=1)
    p.add_argument('--dpi', type=int, default=80)
    p.add_argument('-o', '--out')
    return ap


PASS = {'report': ('report_cmd', 'main'), 'stats': ('stats', 'main'), 'chart': ('charts', 'main')}


def main(argv=None):
    _utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASS:              # 자기 인자 해석기를 가진 명령은 그대로 넘긴다
        import importlib
        mod, fn = PASS[argv[0]]
        try:
            return getattr(importlib.import_module('.' + mod, __package__), fn)(argv[1:]) or 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
        except Exception as e:  # noqa
            print('오류: ' + str(e))
            if os.environ.get('HWPX_NEW_DEBUG'):
                import traceback
                traceback.print_exc()
            return 1
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        return _run(a, ap)
    except Exception as e:  # noqa
        print('오류: ' + str(e))
        if os.environ.get('HWPX_NEW_DEBUG'):
            import traceback
            traceback.print_exc()
        return 1


def _screensaver_active() -> bool:
    if sys.platform != 'win32':
        return False
    try:
        import subprocess
        r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, errors='replace', timeout=20)
        names = r.stdout.lower()
        return '.scr"' in names or 'logonui.exe' in names
    except Exception:  # noqa
        return False


def _doctor():
    from .pdf import available_engines
    e = available_engines()
    ok = True
    print('hwpx_new 환경 점검')
    print(f'  - 파이썬: {sys.version.split()[0]} ({sys.executable})')
    for mod, label in (('lxml', 'lxml'), ('pymupdf', 'pymupdf(PDF 읽기)'), ('PIL', 'pillow(사진)')):
        try:
            __import__(mod)
            print(f'  - {label}: 있음')
        except ImportError:
            ok = False
            print(f'  - {label}: 없음 → 설치: {sys.executable} -m pip install {"pillow" if mod == "PIL" else mod}')
    try:
        from .charts import font_files
        ff = font_files()
        print(f'  - 도표 한글 글꼴: {ff.get("family", "?")} ({os.path.basename(ff["Regular"])})')
    except Exception as ex:  # noqa
        ok = False
        print(f'  - 도표 한글 글꼴: 없음 → {ex}')
    ex_dir = os.path.join(HERE, 'data', 'report_example')
    print(f'  - 보고서 예시(report init): {"있음" if os.path.exists(os.path.join(ex_dir, "report.txt")) else "없음 → 다시 설치하세요"}')
    print('PDF 변환 엔진')
    print(f'  - 한글(Hancom Office, Windows): {"사용 가능" if e["hancom"] else "없음"}')
    print(f'  - LibreOffice: {"있음" if e["libreoffice"] else "없음"} (HWPX 열기 확장이 없으면 실패할 수 있음)')
    print(f'  - 내장 렌더러: 사용 가능 (브라우저: {e["browser"] or "없음 → pymupdf 로 대체"})')
    best = 'hancom' if e['hancom'] else ('libreoffice' if e['libreoffice'] else 'html')
    print(f'→ 기본 사용 엔진: {best}' + ('' if best != 'html' else '  (근사 PDF: 실제 한글 배치와 조금 다를 수 있음)'))
    if e['hancom']:
        print('한글 자동 변환: 한글이 "파일 접근 허용" 창을 띄우면 도구가 자동으로 [접근 허용]을 누릅니다(작업 폴더의 파일만).')
        if _screensaver_active():
            print('  ※ 지금 화면보호기/잠금 화면이 켜져 있는 것 같습니다. 이 상태에서는 자동 클릭이 되지 않으니 화면을 켜고 쓰세요.')
    return 0 if ok else 1


def _doctor_hancom():
    """한글로 내장 예시 서식을 PDF 로 바꿔 보며 승인 창이 자동 처리되는지 점검."""
    import tempfile
    import time
    from . import hancom
    if not hancom.installed():
        print('한글이 설치돼 있지 않아 점검할 수 없습니다.')
        return 1
    src = os.path.join(HERE, 'data', 'sample_template.hwpx')
    out = os.path.join(tempfile.mkdtemp(prefix='hwpx_new_hc_'), 'test.pdf')
    print(chr(10) + '한글 변환 점검(예시 서식 → PDF). 승인 창이 뜨면 자동으로 누릅니다…')
    if _screensaver_active():
        print('  ※ 화면보호기/잠금 화면이 켜져 있는 것 같습니다. 이 상태에서는 자동 클릭이 되지 않습니다. 화면을 켠 뒤 다시 실행하세요.')
    t = time.time()
    ok, msg, info = hancom.export_pdf(src, out, timeout=120)
    took = round(time.time() - t, 1)
    if ok:
        how = info.get('dialogs', '')
        print(f'성공: {took}초, {info.get("pages")}쪽. ' + ('승인 창을 자동으로 처리했습니다.' if ' CLICK' in how else '승인 창 없이 끝났습니다.'))
        return 0
    print(f'실패({took}초): {msg}')
    if info.get('timeline'):
        print('  진행: ' + info['timeline'])
    return 1


def _check(hwpx):
    """HWPX → PDF → 조판 점검(오류가 있으면 1)."""
    from . import layout_qa
    print('조판 점검…')
    return layout_qa.main([hwpx, '--strict'])


def _run(a, ap):
    if a.cmd == 'qa':
        from . import layout_qa
        argv = [a.pdf, '--skip', a.skip, '--colors', a.colors] + (['-o', a.out] if a.out else []) + \
            (['--strict'] if a.strict else [])
        return layout_qa.main(argv)
    if a.cmd == 'gongmun':
        from .gongmun import build
        print('HWPX:', build(a.spec, a.out))
        return _check(a.out) if a.check else 0
    if a.cmd == 'compose':
        from .spec import build
        print('HWPX:', build(a.spec, a.out))
        return _check(a.out) if a.check else 0
    if a.cmd == 'patch':
        from .patch import patch
        for line in patch(a.src, a.ops, a.out, style=a.style):
            print(' -', line)
        print('HWPX:', a.out)
        return _check(a.out) if a.check else 0
    if a.cmd == 'replace':
        from .patch import replace_text_zip
        pairs = [tuple(x.split('=>', 1)) for x in a.pair]
        for k, n in replace_text_zip(a.src, a.out, pairs).items():
            print(f' - "{k}": 본문 {n}곳')
        print('HWPX:', a.out)
        return 0
    if a.cmd == 'diff':
        from .patch import diff_report
        print(diff_report(a.a, a.b))
        return 0
    if a.cmd == 'shrink':
        from .images import shrink_hwpx
        rep, (b, f) = shrink_hwpx(a.src, a.out, dpi=a.dpi)
        for name, kb0, kb1 in rep:
            print(f' - {name}: {kb0}KB → {kb1}KB')
        print(f'문서 {b}KB → {f}KB ({0 if not b else round((1 - f / b) * 100)}% 줄임): {a.out}')
        return 0
    if a.cmd == 'doctor':
        rc = _doctor()
        if a.hancom:
            rc = _doctor_hancom() or rc
        return rc
    if a.cmd == 'format':
        print(open(os.path.join(HERE, 'FORMAT.md'), encoding='utf-8').read())
        return 0
    if a.cmd == 'instructions':
        print(open(os.path.join(HERE, 'data', 'AGENTS.md'), encoding='utf-8').read())
        return 0
    if a.cmd == 'analyze':
        from .analyze import analyze, blueprint_markdown, scaffold_markdown
        bp = analyze(a.template)
        if a.json:
            print(json.dumps([{'idx': b.idx, 'role': b.role, 'class': b.cls, 'text': b.text} for b in bp.blocks],
                             ensure_ascii=False, indent=1))
        else:
            print(blueprint_markdown(bp))
            print('\n---\n## 뼈대 Markdown(이 구조와 표시를 살려 새 목적에 맞게 고쳐 쓰세요)\n\n```markdown')
            print(scaffold_markdown(bp) + '```')
        return 0
    if a.cmd in ('skeleton', 'scaffold'):
        from .analyze import analyze, scaffold_markdown
        md = scaffold_markdown(analyze(a.template))
        if a.out:
            open(a.out, 'w', encoding='utf-8').write(md)
            print(a.out)
        else:
            print(md)
        return 0
    if a.cmd == 'selfcheck':
        from .selfcheck import report, run_selfcheck
        r = run_selfcheck(a.template)
        print(report(r, a.verbose))
        if a.pdf:
            from .pdf import convert
            for nm in ('orig', 'rebuilt'):
                pdf = r[nm][:-5] + '.pdf'
                eng, log = convert(r[nm], pdf)
                print(f'{nm}: {pdf if eng else "PDF 실패"}')
        print(f'(작업 파일: {r["work"]})')
        return 0
    if a.cmd == 'read':
        from .analyze import dump_document
        print(dump_document(a.file))
        return 0
    if a.cmd == 'build':
        from .pipeline import make_report, summarize
        res = make_report(a.template, a.content, a.out, name=a.name, engine=a.engine,
                          autofix=not a.no_autofix, previews=not a.no_preview)
        print(summarize(res))
        return 0
    if a.cmd == 'convert':
        from .pdf import hwp_to_hwpx
        out = a.out or os.path.splitext(a.hwp)[0] + '.hwpx'
        ok, msg = hwp_to_hwpx(a.hwp, out)
        print(msg)
        return 0 if ok else 1
    if a.cmd == 'prompt':
        from .analyze import analyze, blueprint_markdown, scaffold_markdown
        fmt = open(os.path.join(HERE, 'FORMAT.md'), encoding='utf-8').read()
        bp = analyze(a.template)
        print(PROMPT_TMPL.format(request=' '.join(a.request) or '(여기에 원하는 작업을 적으세요)',
                                 analysis=blueprint_markdown(bp), scaffold=scaffold_markdown(bp), fmt=fmt))
        return 0
    if a.cmd == 'setup':
        from . import setup_cmd
        only = [x.strip() for x in a.only.split(',')] if a.only else None
        msgs, n = setup_cmd.run_setup(only=only, yes=a.yes, dry=a.dry_run, home=a.home)
        print('AI 프로그램 연결 결과' + (' (미리보기: 실제로는 고치지 않음)' if a.dry_run else ''))
        print('\n'.join(msgs))
        if a.skill:
            print('- Claude Code 스킬: ' + {'added': '설치했습니다', 'already': '이미 설치돼 있습니다'}.get(
                setup_cmd.install_skill(a.home, a.dry_run), '?'))
        if n and not a.dry_run:
            print('\n→ AI 프로그램을 완전히 종료했다가 다시 실행하면 hwpx_new 도구가 나타납니다.')
        print('→ 채팅형 AI(웹 ChatGPT·Gemini 등)는 `hwpx-new prompt 서식.hwpx "요청"` 으로 만든 글을 붙여 넣으세요.')
        return 0
    if a.cmd == 'hancom-module':
        from . import hancom_module as hm
        if a.action == 'status':
            mods = hm.status()
            print('등록된 한글 자동화 보안 모듈: ' + (', '.join(f'{k} → {v}' for k, v in mods.items()) if mods else '없음'))
            print('※ 등록하면 한글이 "파일 접근 허용" 창을 띄우지 않습니다(이 PC 의 한글 자동화 전체에 적용).')
            return 0
        if a.action == 'remove':
            print('해제했습니다.' if hm.remove() else '등록된 모듈이 없습니다.')
            return 0
        if not a.dll:
            print('--dll 로 FilePathCheckerModule DLL 경로를 주세요. 이 도구는 DLL 을 내려받거나 만들지 않습니다(한글 개발자 자료의 자동화 SDK 에 들어 있음).')
            return 1
        print('이 작업은 이 PC 의 한글 보안 설정을 바꿉니다: 등록한 DLL 이 한글 자동화의 파일 접근을 대신 승인합니다(현재 사용자 레지스트리만, `hancom-module remove` 로 해제).')
        if not a.yes:
            if input('DLL 의 출처를 신뢰하고 계속할까요? [y/N] ').strip().lower() not in ('y', 'yes'):
                print('취소했습니다.')
                return 1
        path = hm.register(a.dll)
        ok, msg = hm.verify()
        print(f'등록: {path}')
        print('확인: ' + ('한글이 모듈을 받아들였습니다(이제 승인 창이 뜨지 않습니다).' if ok else f'한글이 모듈을 받아들이지 않았습니다({msg}). DLL 이 맞는지 확인하거나 `hancom-module remove` 로 해제하세요.'))
        return 0 if ok else 1
    if a.cmd == 'mcp-config':
        py = sys.executable
        cfg = {'mcpServers': {'hwpx_new': {'command': py, 'args': ['-m', 'hwpx_new.mcp_server']}}}
        print('# 공통 JSON (Claude Desktop / Cursor / Windsurf / Antigravity 등의 mcpServers 항목)')
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        print()
        print('# Claude Code')
        print(f'claude mcp add --scope user hwpx_new -- "{py}" -m hwpx_new.mcp_server')
        print()
        print('# Codex CLI (~/.codex/config.toml)')
        print('[mcp_servers.hwpx_new]')
        print(f"command = '{py}'")
        print("args = ['-m', 'hwpx_new.mcp_server']")
        print()
        print('# Gemini CLI (~/.gemini/settings.json 의 mcpServers 에 위 공통 JSON 추가)')
        print()
        print('※ 자동으로 하려면: hwpx-new setup')
        return 0
    if a.cmd == 'photos':
        from .photos import describe_folder
        text, sheet = describe_folder(a.folder, a.out)
        print(text)
        return 0
    if a.cmd == 'preview':
        import pymupdf
        d = pymupdf.open(a.pdf)
        out = a.out or f'{os.path.splitext(a.pdf)[0]}_p{a.page}.png'
        d[a.page - 1].get_pixmap(dpi=a.dpi).save(out)
        print(out)
        return 0
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
