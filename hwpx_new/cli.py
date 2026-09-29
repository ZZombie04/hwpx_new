# -*- coding: utf-8 -*-
"""명령줄 도구: hwpx-new"""
from __future__ import annotations

import argparse
import json
import os
import sys


PROMPT_TMPL = """너는 한글(HWPX) 문서 작성 도우미다. 아래 [서식 분석]은 사용자가 가진 서식 파일을 분석한 결과다.
이 서식의 뼈대(표지·소제목·표·박스·글머리)를 그대로 따르되, [요청]에 맞게 내용을 새로 써서
**[내용 형식]** 문법의 Markdown 으로만 출력하라(설명·머리말 없이 Markdown 본문만, 코드블록으로 감싸도 됨).

규칙
- 사용자가 주지 않은 사실(숫자·인명·날짜)을 지어 넣었다면, Markdown 맨 끝에 `<!-- 지어낸 내용: ... -->` 주석으로 목록을 남겨라.
- 서식의 문체(개조식 ~함/~임, 또는 ~합니다)와 번호 체계(Ⅰ. / 1. / 가.)를 그대로 쓴다.
- 날짜에 요일을 쓰면 실제 요일과 맞아야 한다.

[요청]
{request}

[서식 분석]
{analysis}

[서식 뼈대 초안 — 이 구조를 고쳐 쓴다]
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


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(prog='hwpx-new',
                                 description='한글(HWPX) 서식을 분석해 같은 서식의 새 문서(HWPX+PDF)를 만듭니다.')
    sub = ap.add_subparsers(dest='cmd')

    sub.add_parser('doctor', help='PDF 변환 엔진 등 환경 점검')
    sub.add_parser('format', help='내용 작성 형식 안내 출력')

    p = sub.add_parser('analyze', help='서식 분석 결과 출력')
    p.add_argument('template')
    p.add_argument('--json', action='store_true')

    p = sub.add_parser('scaffold', help='서식 뼈대 Markdown 초안 출력')
    p.add_argument('template')
    p.add_argument('-o', '--out')

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

    sub.add_parser('mcp-config', help='MCP 설정(JSON)을 각 AI 프로그램별로 출력')

    p = sub.add_parser('photos', help='사진 폴더 살펴보기: 목록(촬영일시·크기) + 번호 붙은 한눈에 보기 이미지')
    p.add_argument('folder')
    p.add_argument('-o', '--out', help='한눈에 보기 이미지 저장 경로(기본: 폴더/_photo_sheet.png)')

    p = sub.add_parser('preview', help='PDF 한 쪽을 PNG 로 저장')
    p.add_argument('pdf')
    p.add_argument('--page', type=int, default=1)
    p.add_argument('--dpi', type=int, default=80)
    p.add_argument('-o', '--out')

    a = ap.parse_args(argv)
    try:
        return _run(a, ap)
    except Exception as e:  # noqa
        print('오류: ' + str(e))
        return 1


def _run(a, ap):
    if a.cmd == 'doctor':
        from .pdf import available_engines
        e = available_engines()
        print('PDF 변환 엔진 상태')
        print(f'  - 한글(Hancom Office, Windows): {"사용 가능" if e["hancom"] else "없음"}')
        print(f'  - LibreOffice: {"있음" if e["libreoffice"] else "없음"} (HWPX 열기 확장이 없으면 실패할 수 있음)')
        print(f'  - 내장 렌더러: 사용 가능 (브라우저: {e["browser"] or "없음 → pymupdf 로 대체"})')
        best = 'hancom' if e['hancom'] else ('libreoffice' if e['libreoffice'] else 'html')
        print(f'→ 기본 사용 엔진: {best}' + ('' if best != 'html' else '  (근사 PDF: 실제 한글 배치와 조금 다를 수 있음)'))
        return 0
    if a.cmd == 'format':
        print(open(os.path.join(os.path.dirname(__file__), 'FORMAT.md'), encoding='utf-8').read())
        return 0
    if a.cmd == 'analyze':
        from .analyze import analyze, blueprint_markdown
        bp = analyze(a.template)
        if a.json:
            print(json.dumps([{'idx': b.idx, 'role': b.role, 'text': b.text} for b in bp.blocks],
                             ensure_ascii=False, indent=1))
        else:
            print(blueprint_markdown(bp))
        return 0
    if a.cmd == 'scaffold':
        from .analyze import analyze, scaffold_markdown
        md = scaffold_markdown(analyze(a.template))
        if a.out:
            open(a.out, 'w', encoding='utf-8').write(md)
            print(a.out)
        else:
            print(md)
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
        here = os.path.dirname(__file__)
        fmt = open(os.path.join(here, 'FORMAT.md'), encoding='utf-8').read()
        bp = analyze(a.template)
        print(PROMPT_TMPL.format(request=a.request or '(여기에 원하는 작업을 적으세요)',
                                 analysis=blueprint_markdown(bp), scaffold=scaffold_markdown(bp), fmt=fmt))
        return 0
    if a.cmd == 'mcp-config':
        py = sys.executable
        cfg = {'mcpServers': {'hwpx_new': {'command': py, 'args': ['-m', 'hwpx_new.mcp_server']}}}
        print('# 공통 JSON (Claude Desktop / Cursor / Windsurf / Antigravity 등의 mcpServers 항목)')
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        print()
        print('# Claude Code')
        print(f'claude mcp add hwpx_new -- "{py}" -m hwpx_new.mcp_server')
        print()
        print('# Codex CLI (~/.codex/config.toml)')
        print('[mcp_servers.hwpx_new]')
        print(f'command = "{py}"'.replace(chr(92), '/'))
        print('args = ["-m", "hwpx_new.mcp_server"]')
        print()
        print('# Gemini CLI (~/.gemini/settings.json 의 mcpServers 에 위 공통 JSON 추가)')
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
