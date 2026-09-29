# -*- coding: utf-8 -*-
"""MCP 서버(stdio): Claude Desktop/Code, Cursor, Codex, Gemini CLI, Antigravity 등 MCP 를 지원하는 모든 AI 에서 사용."""
from __future__ import annotations

import os

try:  # mcp 2.x
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

mcp = _Server('hwpx_new')

GUIDE = os.path.join(os.path.dirname(__file__), 'FORMAT.md')


@mcp.tool()
def hwpx_start_here() -> str:
    """가장 먼저 호출. 이 도구 모음의 사용 순서와 규칙을 알려 준다."""
    return (
        '## hwpx_new 사용 순서\n'
        '1. hwpx_analyze(template_path): 사용자가 준 HWPX 서식을 분석한다. 표지·소제목·표·박스 구조와 문서 뼈대를 파악한다.\n'
        '2. 사용자의 요청(예: 계획서 → 결과보고서)에 맞게 서식의 뼈대를 따라 내용을 새로 쓴다. hwpx_format_guide 로 문법 확인.\n'
        '   - 사용자가 주지 않은 사실을 지어 넣었다면 최종 답변에서 반드시 밝힌다.\n'
        '3. hwpx_build(template_path, content, output_dir): HWPX + PDF 를 한 번에 만든다. 조판 점검과 자동 보정이 포함되어 있다.\n'
        '   - 사용자가 사진을 줬다면: hwpx_photos(폴더) → hwpx_photo_sheet(폴더)로 사진을 보고, 내용에 `![캡션](경로)` / `:::photos` 로 넣는다.\n'
        '4. hwpx_preview(pdf_path, page): 결과 PDF 를 눈으로 확인한다. 어색하면 내용을 고쳐 3번을 다시 호출한다.\n'
        '5. 사용자에게 HWPX·PDF 경로와 지어 넣은 내용(있다면)을 알린다.\n'
        '※ .hwp(옛 형식)는 한글에서 HWPX 로 다시 저장해야 한다.')


@mcp.tool()
def hwpx_doctor() -> str:
    """PDF 변환 엔진(한글/LibreOffice/내장) 사용 가능 여부를 점검한다."""
    from .pdf import available_engines
    e = available_engines()
    return (f'한글(Hancom): {e["hancom"]}\nLibreOffice: {e["libreoffice"]}\n내장 렌더러: 가능 (브라우저 {e["browser"]})\n'
            + ('한글이 있어 실제와 동일한 PDF 가 만들어진다.' if e['hancom'] else
               '한글이 없어 근사 PDF 가 만들어질 수 있다(쪽 배치가 실제와 조금 다를 수 있음).'))


@mcp.tool()
def hwpx_format_guide() -> str:
    """내용 작성 문법(Markdown 확장 / JSON 블록)을 돌려준다."""
    return open(GUIDE, encoding='utf-8').read()


@mcp.tool()
def hwpx_analyze(template_path: str) -> str:
    """HWPX 서식을 분석해 문서 구조(표지, 소제목, 표, 박스, 글머리)와, 그 뼈대를 따르는 Markdown 초안을 돌려준다."""
    from .analyze import analyze, blueprint_markdown, scaffold_markdown
    bp = analyze(template_path)
    return blueprint_markdown(bp) + '\n\n---\n## 뼈대 초안(이 구조를 새 목적에 맞게 고쳐 쓰세요)\n\n```markdown\n' + \
        scaffold_markdown(bp) + '```\n'


@mcp.tool()
def hwpx_read(path: str) -> str:
    """HWPX 문서의 본문을 Markdown 으로 읽는다(참고 자료·기존 문서 확인용)."""
    from .analyze import dump_document
    return dump_document(path)


@mcp.tool()
def hwpx_build(template_path: str, content: str, output_dir: str, name: str = '', engine: str = '') -> str:
    """서식 + 내용으로 HWPX 와 PDF 를 만든다(조판 자동 점검·보정 포함).

    content: Markdown(확장) 또는 JSON 문자열, 혹은 그 내용이 담긴 파일 경로.
    output_dir: 결과를 저장할 폴더. name: 파일 이름(생략하면 제목). engine: hancom|libreoffice|html(생략 시 자동).
    """
    from .pipeline import make_report, summarize
    res = make_report(template_path, content, output_dir, name=name or None, engine=engine or None)
    return summarize(res)


@mcp.tool()
def hwpx_convert_hwp(hwp_path: str) -> str:
    """옛 .hwp 파일을 .hwpx 로 변환한다(Windows + 한글 필요). 결과 경로를 돌려준다."""
    from .pdf import hwp_to_hwpx
    out = os.path.splitext(hwp_path)[0] + '.hwpx'
    ok, msg = hwp_to_hwpx(hwp_path, out)
    return msg if ok else '변환 실패: ' + msg


@mcp.tool()
def hwpx_photos(folder: str) -> str:
    """사진 폴더(또는 사진 파일)를 살펴본다: 촬영 시각 순 목록과 번호가 붙은 한눈에 보기 이미지 경로를 돌려준다.
    이어서 hwpx_photo_sheet 로 그 이미지를 보고 각 사진이 무엇인지 파악한 뒤 보고서의 알맞은 위치에 넣는다."""
    from .photos import describe_folder
    text, _sheet = describe_folder(folder)
    return text


@mcp.tool()
def hwpx_photo_sheet(folder: str) -> Image:
    """hwpx_photos 가 만든 '번호 붙은 사진 한눈에 보기' 이미지를 돌려준다(사진 내용을 파악할 때 사용)."""
    from .photos import describe_folder
    _text, sheet = describe_folder(folder)
    with open(sheet, 'rb') as f:
        return Image(data=f.read(), format='png')


@mcp.tool()
def hwpx_preview(pdf_path: str, page: int = 1, dpi: int = 80) -> Image:
    """PDF 의 한 쪽을 이미지로 돌려준다(결과를 눈으로 확인할 때 사용)."""
    import pymupdf
    d = pymupdf.open(pdf_path)
    pix = d[max(0, min(page, len(d)) - 1)].get_pixmap(dpi=dpi)
    return Image(data=pix.tobytes('png'), format='png')


def main():
    mcp.run()


if __name__ == '__main__':
    main()
