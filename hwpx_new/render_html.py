# -*- coding: utf-8 -*-
"""내장 미리보기 렌더러: HWPX → HTML → PDF (한글/LibreOffice 가 없는 환경의 대체 경로, '근사' 결과)."""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import tempfile

from .analyze import ptext
from .package import HP, Package, NS
from .analyze import page_info


def find_browsers():
    """Chrome 계열을 먼저, Edge 를 나중에(환경에 따라 Edge 의 헤드리스 인쇄가 막혀 있는 경우가 있음)."""
    cands = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ]
    pre = []
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'msedge',
              'microsoft-edge'):
        w = shutil.which(n)
        if w:
            pre.append(w)
    out = []
    for c in pre + cands:
        if os.path.exists(c) and c not in out:
            out.append(c)
    return out


def find_browser():
    bs = find_browsers()
    return bs[0] if bs else None


def _bw(width: str) -> float:
    try:
        return max(0.4, float(width.split()[0]) * 2.83)
    except Exception:  # noqa
        return 0.5


def _border_css(head, bf_id):
    b = head.borders.get(str(bf_id))
    if not b:
        return ''
    css = []
    for side in ('left', 'right', 'top', 'bottom'):
        typ, w = b[side]
        if typ in (None, 'NONE'):
            css.append(f'border-{side}:none')
        else:
            style = 'dashed' if 'DASH' in typ else ('dotted' if 'DOT' in typ else ('double' if 'DOUBLE' in typ else 'solid'))
            css.append(f'border-{side}:{_bw(w):.2f}pt {style} #000')
    if b['gradient']:
        css.append(f'background:linear-gradient(to right,{b["gradient"][0]},{b["gradient"][-1]})')
    elif b['fill']:
        css.append(f'background:{b["fill"]}')
    return ';'.join(css)


class Renderer:
    def __init__(self, pkg: Package):
        self.pkg = pkg
        self.head = pkg.header()
        self.root = pkg.section_root(0)
        self.page = page_info(self.root)

    def para_css(self, p):
        pp = self.head.para.get(p.get('paraPrIDRef'), {})
        al = {'JUSTIFY': 'justify', 'CENTER': 'center', 'RIGHT': 'right', 'LEFT': 'left'}.get(pp.get('align'), 'left')
        left, intent = pp.get('left', 0), pp.get('intent', 0)
        ml = (left - min(intent, 0)) / 100
        css = f'text-align:{al};line-height:{pp.get("line", 130) / 100:.2f};margin:0;margin-left:{ml:.1f}pt;text-indent:{intent / 100:.1f}pt;'
        if p.get('pageBreak') == '1':
            css += 'page-break-before:always;break-before:page;'
        return css

    def render_p(self, p, top=False, in_cell=False):
        out = []
        tables = [r.find(HP + 'tbl') for r in p.findall(HP + 'run') if r.find(HP + 'tbl') is not None]
        spans = []
        for run in p.findall(HP + 'run'):
            txt = ''.join(''.join(t.itertext()) for t in run.findall(HP + 't'))
            if not txt:
                continue
            txt = ''.join('●' if '\uf000' <= c <= '\uf0ff' else c for c in txt)
            ch = self.head.char.get(run.get('charPrIDRef'), {})
            style = f'font-size:{ch.get("height", 1000) / 100:.1f}pt;color:{ch.get("color", "#000")};'
            if ch.get('bold'):
                style += 'font-weight:bold;'
            spans.append(f'<span style="{style}">{html.escape(txt).replace(" ", "&nbsp;") if txt.strip() == "" else html.escape(txt)}</span>')
        pb = p.get('pageBreak') == '1'
        if tables:
            if pb:
                out.append('<div style="page-break-before:always;break-before:page"></div>')
            for t in tables:
                out.append(self.render_table(t))
            return ''.join(out)
        css = self.para_css(p)
        if not spans:
            if in_cell:
                out.append('<div style="height:0;line-height:0;font-size:0"></div>')
            else:
                out.append(f'<p style="{css}height:15.6pt">&nbsp;</p>')
        else:
            out.append(f'<p style="{css}">{"".join(spans)}</p>')
        return ''.join(out)

    def render_table(self, tbl):
        w = int(tbl.find(HP + 'sz').get('width')) / 100
        cols = int(tbl.get('colCnt'))
        widths = [0.0] * cols
        for tc in tbl.iter(HP + 'tc'):
            a, s, z = tc.find(HP + 'cellAddr'), tc.find(HP + 'cellSpan'), tc.find(HP + 'cellSz')
            if int(s.get('colSpan')) == 1:
                widths[int(a.get('colAddr'))] = int(z.get('width')) / 100
        rest = w - sum(widths)
        zeros = [i for i, x in enumerate(widths) if x == 0]
        for i in zeros:
            widths[i] = rest / len(zeros) if rest > 0 else w / cols
        h = ['<table style="border-collapse:collapse;table-layout:fixed;width:%.1fpt;margin:0">' % w]
        h.append('<colgroup>' + ''.join(f'<col style="width:{x:.1f}pt">' for x in widths) + '</colgroup>')
        for tr in tbl.findall(HP + 'tr'):
            h.append('<tr>')
            for tc in tr.findall(HP + 'tc'):
                a, s, z = tc.find(HP + 'cellAddr'), tc.find(HP + 'cellSpan'), tc.find(HP + 'cellSz')
                m = tc.find(HP + 'cellMargin')
                sub = tc.find(HP + 'subList')
                va = {'CENTER': 'middle', 'BOTTOM': 'bottom'}.get(sub.get('vertAlign'), 'top')
                pad = f'padding:{int(m.get("top", 141)) / 100:.1f}pt {int(m.get("right", 510)) / 100:.1f}pt ' \
                      f'{int(m.get("bottom", 141)) / 100:.1f}pt {int(m.get("left", 510)) / 100:.1f}pt;'
                inner = ''.join(self.render_p(p, in_cell=True) for p in sub.findall(HP + 'p'))
                cc = int(a.get('colAddr'))
                tw = sum(widths[cc:cc + int(s.get('colSpan'))])
                css = f'width:{tw:.1f}pt;max-width:{tw:.1f}pt;overflow:hidden;height:{int(z.get("height")) / 100:.1f}pt;vertical-align:{va};{pad}' \
                      f'{_border_css(self.head, tc.get("borderFillIDRef"))}'
                h.append(f'<td colspan="{s.get("colSpan")}" rowspan="{s.get("rowSpan")}" style="{css}">{inner}</td>')
            h.append('</tr>')
        h.append('</table>')
        return ''.join(h)

    def to_html(self):
        pg = self.page
        body = ''.join(self.render_p(p, True) for p in self.root.findall(HP + 'p'))
        return f'''<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {pg["width"] / 100:.1f}pt {pg["height"] / 100:.1f}pt; margin: {pg["top"] / 100:.1f}pt {pg["right"] / 100:.1f}pt {pg["bottom"] / 100:.1f}pt {pg["left"] / 100:.1f}pt; }}
*{{box-sizing:border-box}}
body {{ font-family: "Malgun Gothic","맑은 고딕","Noto Sans KR","Noto Sans CJK KR","Apple SD Gothic Neo",sans-serif; margin:0; }}
body {{ word-break: keep-all; overflow-wrap: anywhere; }}
table {{ page-break-inside: auto; }} tr {{ page-break-inside: avoid; }}
</style></head><body>{body}</body></html>'''


def render_pdf(hwpx, pdf):
    try:
        pkg = Package(hwpx)
        doc = Renderer(pkg).to_html()
    except Exception as e:  # noqa
        return False, f'HTML 변환 실패: {e}'
    tmpd = tempfile.mkdtemp()
    try:
        hp = os.path.join(tmpd, 'doc.html')
        open(hp, 'w', encoding='utf-8').write(doc)
        for b in find_browsers():
            for flag in ('--headless=new', '--headless'):
                try:
                    if os.path.exists(pdf):
                        os.remove(pdf)
                except OSError:
                    pass
                prof = tempfile.mkdtemp(dir=tmpd)
                extra = ['--no-sandbox'] if hasattr(os, 'geteuid') and os.geteuid() == 0 else []
                try:
                    subprocess.run([b, flag, '--disable-gpu', f'--user-data-dir={prof}', *extra,
                                    '--no-pdf-header-footer', f'--print-to-pdf={os.path.abspath(pdf)}',
                                    'file:///' + hp.replace(chr(92), '/')],
                                   capture_output=True, timeout=90)
                except Exception:  # noqa
                    pass
                if os.path.exists(pdf) and os.path.getsize(pdf) > 1000:
                    return True, ''
        try:
            import pymupdf
            pg = Renderer(pkg).page
            W, H = pg['width'] / 100, pg['height'] / 100
            mb = pymupdf.Rect(0, 0, W, H)
            where = pymupdf.Rect(pg['left'] / 100, pg['top'] / 100, W - pg['right'] / 100, H - pg['bottom'] / 100)
            story = pymupdf.Story(html=doc)
            w = pymupdf.DocumentWriter(pdf)
            more = 1
            while more:
                dev = w.begin_page(mb)
                more, _ = story.place(where)
                story.draw(dev)
                w.end_page()
            w.close()
            return True, ''
        except Exception as e:  # noqa
            return False, f'PDF 생성 실패(브라우저 없음/pymupdf 오류): {e}'
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
