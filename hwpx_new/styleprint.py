# -*- coding: utf-8 -*-
"""문서의 '겉모양 지문': 스타일 번호(id) 대신 실제 값(글자 크기·색·굵기·정렬·들여쓰기·줄간격·테두리…)으로 블록을 요약한다.

서식 재현이 얼마나 정확한지 원본과 결과를 비교(self-check)할 때 쓴다.
"""
from __future__ import annotations

from .analyze import ptext
from .package import HC, HH, HP, NS

_HC = NS['hc']


def _first(el, path):
    r = el.xpath(path, namespaces=NS)
    return r[0] if r else None


class Styles:
    """header.xml 의 글자·문단·테두리 모양을 id → 실제 값으로 풀어 둔다."""

    def __init__(self, head_root):
        self.faces = {}
        for ff in head_root.iter(HH + 'fontface'):
            lang = ff.get('lang')
            for f in ff.findall(HH + 'font'):
                self.faces[(lang, f.get('id'))] = f.get('face')
        self.char = {}
        for cp in head_root.iter(HH + 'charPr'):
            fr = cp.find(HH + 'fontRef')
            ul = cp.find(HH + 'underline')
            face = self.faces.get(('HANGUL', fr.get('hangul'))) if fr is not None else None
            self.char[cp.get('id')] = {
                'size': int(cp.get('height', '1000')),
                'color': (cp.get('textColor') or '#000000').upper(),
                'shade': (cp.get('shadeColor') or 'none').upper(),
                'bold': cp.find(HH + 'bold') is not None,
                'italic': cp.find(HH + 'italic') is not None,
                'under': (ul.get('type') if ul is not None and ul.get('type') != 'NONE' else None),
                'face': face,
                'ratio': (cp.find(HH + 'ratio').get('hangul') if cp.find(HH + 'ratio') is not None else '100'),
                'spacing': (cp.find(HH + 'spacing').get('hangul') if cp.find(HH + 'spacing') is not None else '0'),
            }
        self.para = {}
        for pp in head_root.iter(HH + 'paraPr'):
            al = pp.find(HH + 'align')
            m = _first(pp, './/hh:margin')
            ls = _first(pp, './/hh:lineSpacing')

            def mv(tag):
                if m is None:
                    return 0
                e = m.find('{%s}%s' % (_HC, tag))
                return int(e.get('value')) if e is not None else 0
            ht = pp.find(HH + 'heading')
            self.para[pp.get('id')] = {
                'align': al.get('horizontal') if al is not None else 'JUSTIFY',
                'left': mv('left'), 'right': mv('right'), 'intent': mv('intent'),
                'prev': mv('prev'), 'next': mv('next'),
                'ls_type': ls.get('type') if ls is not None else 'PERCENT',
                'ls': int(ls.get('value')) if ls is not None else 130,
                'heading': (ht.get('type') if ht is not None else 'NONE'),
                'keep_next': (pp.find(HH + 'breakSetting').get('keepWithNext') if pp.find(HH + 'breakSetting') is not None else '0'),
            }
        self.border = {}
        for bf in head_root.iter(HH + 'borderFill'):
            info = {}
            wb = bf.find('.//' + HC + 'winBrush')
            face = wb.get('faceColor') if wb is not None else None
            gr = bf.find('.//' + HC + 'gradation')
            if gr is not None:
                face = 'GRAD:' + ','.join(c.get('value', '') for c in gr.findall(HC + 'color'))
            info['fill'] = (face or 'none').upper()
            for side in ('left', 'right', 'top', 'bottom'):
                e = bf.find(HH + side + 'Border')
                if e is None or e.get('type') in (None, 'NONE'):
                    info[side] = ('NONE', '', '')          # 안 보이는 선은 굵기·색을 비교하지 않는다
                else:
                    try:
                        w = round(float((e.get('width') or '0.1').split()[0]) / 0.05) * 0.05
                    except ValueError:
                        w = 0.1
                    info[side] = (e.get('type'), f'{w:.2f}', (e.get('color') or '').upper())
            self.border[bf.get('id')] = info


def _run_fp(run, st: Styles):
    c = st.char.get(run.get('charPrIDRef'), {})
    return (c.get('size'), c.get('color'), c.get('bold'), c.get('italic'), c.get('under'), c.get('face'),
            c.get('shade'))


def para_fp(p, st: Styles):
    """문단 하나(중첩 표 제외)의 겉모양."""
    pp = st.para.get(p.get('paraPrIDRef'), {})
    runs = []
    for r in p.findall(HP + 'run'):
        txt = ''.join(''.join(t.itertext()) for t in r.findall(HP + 't'))
        if not txt.strip():
            continue
        fp = _run_fp(r, st)
        if runs and runs[-1][0] == fp:
            runs[-1][1] += txt
        else:
            runs.append([fp, txt])
    return {
        'align': pp.get('align'), 'left': pp.get('left'), 'right': pp.get('right'), 'intent': pp.get('intent'),
        'prev': pp.get('prev'), 'next': pp.get('next'), 'ls': (pp.get('ls_type'), pp.get('ls')),
        'pb': p.get('pageBreak') == '1',
        'runs': [(a, b) for a, b in runs],
        'text': ptext(p),
    }


def _bf_fp(bid, st: Styles):
    b = st.border.get(str(bid))
    if not b:
        return None
    return (b['fill'], b['left'], b['right'], b['top'], b['bottom'])


def cell_paras(tc):
    sub = tc.find(HP + 'subList')
    return sub.findall(HP + 'p') if sub is not None else []


def table_fp(tbl, st: Styles):
    cells = []
    total_w = int(tbl.find(HP + 'sz').get('width')) or 1
    for tr in tbl.findall(HP + 'tr'):
        for tc in tr.findall(HP + 'tc'):
            ad = tc.find(HP + 'cellAddr')
            sp = tc.find(HP + 'cellSpan')
            sz = tc.find(HP + 'cellSz')
            mar = tc.find(HP + 'cellMargin')
            cells.append({
                'r': int(ad.get('rowAddr')), 'c': int(ad.get('colAddr')),
                'rs': int(sp.get('rowSpan')), 'cs': int(sp.get('colSpan')),
                'w': round(int(sz.get('width')) / total_w, 3),
                'bf': _bf_fp(tc.get('borderFillIDRef'), st),
                'va': (tc.find(HP + 'subList').get('vertAlign') if tc.find(HP + 'subList') is not None else None),
                'mar': (mar.get('left'), mar.get('right'), mar.get('top'), mar.get('bottom')) if mar is not None else None,
                'paras': [para_fp(p, st) for p in cell_paras(tc)],
            })
    pos = tbl.find(HP + 'pos')
    return {'rows': int(tbl.get('rowCnt')), 'cols': int(tbl.get('colCnt')), 'width': total_w,
            'inline': (pos.get('treatAsChar') if pos is not None else None), 'cells': cells,
            'cellSpacing': tbl.get('cellSpacing')}


def block_fp(p, st: Styles):
    """최상위 문단 → 지문(표면 dict). 표를 품은 문단은 kind='t'."""
    tbl = None
    for run in p.findall(HP + 'run'):
        t = run.find(HP + 'tbl')
        if t is not None:
            tbl = t
            break
    if tbl is not None:
        return {'kind': 't', 'outer': para_fp(p, st), 'tbl': table_fp(tbl, st)}
    has_obj = any(ch.tag.split('}')[1] in ('pic', 'rect', 'line', 'ellipse', 'container', 'ole', 'polygon', 'arc',
                                              'curve', 'textart', 'equation') for r in p.findall(HP + 'run') for ch in r)
    f = para_fp(p, st)
    if not f['text'].strip():
        return {'kind': 'image' if has_obj else 'blank', 'outer': f}
    return {'kind': 'p', 'outer': f}


def blank_height(fp, st_size=1000):
    """빈 줄 하나가 차지하는 대략의 높이(pt)."""
    o = fp['outer']
    ls = o['ls'][1] if o['ls'][0] == 'PERCENT' else 130
    size = 10.0
    return size * 1.2 * (ls / 100.0) + (o['prev'] + o['next']) / 100.0


# ---------------------------------------------------------------- 비교
TOL = {'left': 120, 'right': 120, 'intent': 120, 'prev': 60, 'next': 60}


def _diff_para(a, b, path, out):
    for k in ('align', 'left', 'right', 'intent', 'prev', 'next', 'ls', 'pb'):
        x, y = a[k], b[k]
        if x == y:
            continue
        if k == 'align' and {x, y} <= {'JUSTIFY', 'LEFT'}:
            continue
        if k in TOL and abs(x - y) <= TOL[k]:
            continue          # 한글이 문단마다 조금씩 다르게 저장하는 들여쓰기·간격 오차는 같은 모양으로 본다
        if k == 'ls' and x[0] == y[0] and abs(x[1] - y[1]) <= 5:
            continue
        out.append((path + '.' + k, x, y))
    ra, rb = a['runs'], b['runs']
    if [x[0] for x in ra] != [x[0] for x in rb]:
        # 글자 모양의 차이를 항목별로 풀어 보고
        fa, fb = [x[0] for x in ra], [x[0] for x in rb]
        names = ('size', 'color', 'bold', 'italic', 'under', 'face', 'shade')
        if len(fa) == len(fb):
            for i, (x, y) in enumerate(zip(fa, fb)):
                for j, nm in enumerate(names):
                    if x[j] != y[j]:
                        out.append((f'{path}.run{i}.{nm}', x[j], y[j]))
        else:
            out.append((path + '.runs(개수/구성)', [x[0][:4] for x in ra][:3], [x[0][:4] for x in rb][:3]))


def diff_blocks(a, b, path='blk'):
    out = []
    if a['kind'] != b['kind']:
        out.append((path + '.kind', a['kind'], b['kind']))
        return out
    if a['kind'] in ('p', 'image', 'blank'):
        _diff_para(a['outer'], b['outer'], path, out)
    else:
        _diff_para(a['outer'], b['outer'], path + '.outer', out)
        ta, tb = a['tbl'], b['tbl']
        if (ta['rows'], ta['cols']) != (tb['rows'], tb['cols']):
            out.append((path + '.tbl.shape', (ta['rows'], ta['cols']), (tb['rows'], tb['cols'])))
        if ta['inline'] != tb['inline']:
            out.append((path + '.tbl.inline', ta['inline'], tb['inline']))
        ca = {(c['r'], c['c']): c for c in ta['cells']}
        cb = {(c['r'], c['c']): c for c in tb['cells']}
        for key in sorted(ca):
            if key not in cb:
                out.append((path + f'.cell{key}', 'exists', 'missing'))
                continue
            x, y = ca[key], cb[key]
            if abs(x['w'] - y['w']) > 0.04:
                out.append((path + f'.cell{key}.w', x['w'], y['w']))
            if (x['rs'], x['cs']) != (y['rs'], y['cs']):
                out.append((path + f'.cell{key}.span', (x['rs'], x['cs']), (y['rs'], y['cs'])))
            if x['bf'] != y['bf']:
                out.append((path + f'.cell{key}.border', x['bf'], y['bf']))
            if x['va'] != y['va']:
                out.append((path + f'.cell{key}.vertAlign', x['va'], y['va']))
            if x['mar'] != y['mar']:
                out.append((path + f'.cell{key}.margin', x['mar'], y['mar']))
            for i, (pa, pb) in enumerate(zip(x['paras'], y['paras'])):
                _diff_para(pa, pb, path + f'.cell{key}.p{i}', out)
    return out
