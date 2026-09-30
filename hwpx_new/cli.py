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

    sub.add_parser('doctor', help='환경 점검(한글·PDF 엔진·자동 승인 등)')
    sub.add_parser('format', help='내용 작성 형식 안내 출력')
    sub.add_parser('instructions', help='AI 작업 지침(AGENTS.md) 출력 — 채팅형 AI 에 붙여 넣을 때')

    p = sub.add_parser('analyze', help='서식 분석 결과 출력(서식 종류·블록·뼈대 Markdown)')
    p.add_argument('template')
    p.add_argument('--json', action='store_true')

    for nm in ('skeleton', 'scaffold'):
        p = sub.add_parser(nm, help='서식을 그대로 다시 만드는 뼈대 Markdown 출력(AI 가 글만 고쳐 쓰는 출발점)')
        p.add_argument('template')
        p.add_argument('-o', '--out')

    p = sub.add_parser('selfcheck', help='서식을 다시 조립해 원본과 모양이 얼마나 같은지 점검(서식 재현도 %)')
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
    p.add_argument('request', nargs='?', default='', help='예: 이 계획서를 결과보고서로 바꿔줘. 이수 24명...')

    p = sub.add_parser('setup', help='설치된 AI 프로그램(Claude·Codex·Gemini·Cursor…)에 MCP 자동 연결')
    p.add_argument('--yes', '-y', action='store_true', help='묻지 않고 모두 연결')
    p.add_argument('--dry-run', action='store_true', help='고치지 않고 무엇을 할지만 보여 줌')
    p.add_argument('--only', help='쉼표로 구분: claude-code,claude-desktop,codex,gemini,cursor,windsurf')
    p.add_argument('--home', help=argparse.SUPPRESS)
    p.add_argument('--skill', action='store_true', help='Claude Code 스킬(SKILL.md)도 설치')

    sub.add_parser('mcp-config', help='MCP 설정 문구를 AI 프로그램별로 출력(직접 붙여 넣을 때)')

    p = sub.add_parser('photos', help='사진 폴더 살펴보기: 목록(촬영일시·크기) + 번호 붙은 한눈에 보기 이미지')
    p.add_argument('folder')
    p.add_argument('-o', '--out', help='한눈에 보기 이미지 저장 경로(기본: 폴더/_photo_sheet.png)')

    p = sub.add_parser('preview', help='PDF 한 쪽을 PNG 로 저장')
    p.add_argument('pdf')
    p.add_argument('--page', type=int, default=1)
    p.add_argument('--dpi', type=int, default=80)
    p.add_argument('-o', '--out')
    return ap


def main(argv=None):
    _utf8()
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


def _run(a, ap):
    if a.cmd == 'doctor':
        return _doctor()
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
        print(PROMPT_TMPL.format(request=a.request or '(여기에 원하는 작업을 적으세요)',
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
