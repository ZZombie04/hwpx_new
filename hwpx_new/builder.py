# -*- coding: utf-8 -*-
"""서식 복제 빌더: 분석된 서식의 요소를 그대로 복제해 새 내용으로 채운 HWPX 를 만든다."""
from __future__ import annotations

import copy
import math
import os
import re
import statistics

from lxml import etree

from collections import Counter

from .analyze import (ROMAN as ROMAN_CHARS, Block, Blueprint, analyze, bullet_marker, cell_paragraphs, first_char_id,
                      heading_class, is_bullet_start, ptext, table_of)
from .images import (ImageError, MM, fit_size, next_image_index, pic_run, prepare_for_box, prepare_image,  # noqa: F401
                     register_images)
from .package import HH, HP, NS

HEADING_SPLIT = re.compile(r'^(\S{1,6}\s*[\.\)]\s*)(.*)$', re.S)


class BuildError(Exception):
    pass


def vkey(e, ncols):
    """세로 경계선 e(0=맨 왼쪽 … ncols=맨 오른쪽)의 종류."""
    if e <= 0:
        return 'outer_l'
    if e >= ncols:
        return 'outer_r'
    if e == 1:
        return 'v_first'
    if e == ncols - 1:
        return 'v_last'
    return 'v_mid'


def hkey(e, nrows, nh):
    """가로 경계선 e(0=맨 위 … nrows=맨 아래)의 종류. nh=머리 줄 수."""
    if e <= 0:
        return 'h_top'
    if e >= nrows:
        return 'h_bottom'
    if nh and e == nh:
        return 'h_headbottom'
    if e < nh:
        return 'h_headmid'
    return 'h_mid'


def ccls(c, cs, ncols):
    """칸이 놓인 열 종류."""
    if cs >= ncols:
        return 'full'
    if c == 0:
        return 'first'
    if c + cs >= ncols:
        return 'last'
    return 'mid'


V_FALL = {'outer_l': ['outer_l'], 'outer_r': ['outer_r'], 'v_first': ['v_first', 'v_mid', 'v_last'],
          'v_mid': ['v_mid', 'v_first', 'v_last'], 'v_last': ['v_last', 'v_mid', 'v_first']}
H_FALL = {'h_top': ['h_top'], 'h_bottom': ['h_bottom'], 'h_headbottom': ['h_headbottom', 'h_mid', 'h_bottom'],
          'h_headmid': ['h_headmid', 'h_mid', 'h_headbottom'], 'h_mid': ['h_mid']}


# ---------------------------------------------------------------- 유틸
def strip_ls(el):
    for ls in list(el.iter(HP + 'linesegarray')):
        ls.getparent().remove(ls)


def own_ts(p):
    return [t for r in p.findall(HP + 'run') for t in r.findall(HP + 't')]


def _set_t(t, text):
    for ch in list(t):
        t.remove(ch)
    t.text = text


def set_text(p, text):
    """문단의 첫 텍스트 노드에 text, 나머지는 비운다(서식 run 은 유지)."""
    ts = own_ts(p)
    if not ts:
        runs = p.findall(HP + 'run')
        target = None
        for r in runs:
            if r.find(HP + 'secPr') is None and r.find(HP + 'ctrl') is None:
                target = r
                break
        if target is None:
            target = etree.SubElement(p, HP + 'run', charPrIDRef='0')
        t = etree.SubElement(target, HP + 't')
        _set_t(t, text)
        return
    # 글이 있는 첫 덩어리에 넣는다(앞쪽 공백만 있는 덩어리의 글자 모양을 따르지 않도록)
    main = next((t for t in ts if ''.join(t.itertext()).strip()), ts[0])
    for t in ts:
        _set_t(t, text if t is main else '')


def set_heading_text(p, text):
    """'Ⅰ. ' 번호 run + 제목 run 으로 나뉜 소제목 문단 처리."""
    ts = own_ts(p)
    nonempty = [t for t in ts if ''.join(t.itertext()).strip()]
    m = HEADING_SPLIT.match(text)
    if len(nonempty) >= 2 and m:
        _set_t(nonempty[0], m.group(1))
        _set_t(nonempty[1], m.group(2))
        for t in nonempty[2:]:
            _set_t(t, '')
    else:
        set_text(p, text)


def set_bullet_text(p, text, marker=None):
    ts = own_ts(p)
    k = None
    for i, t in enumerate(ts):
        if is_bullet_start(''.join(t.itertext()) + 'x'):
            k = i
            break
    if k is None:
        set_text(p, (marker or '') + text)
        return
    cur = ''.join(ts[k].itertext())
    mk = bullet_marker(cur + 'x') if marker is None else marker
    _set_t(ts[k], mk + text)
    for t in ts[k + 1:]:
        _set_t(t, '')


def dwidth(s: str) -> float:
    return sum(1.0 if ord(c) > 0x2E7F else 0.55 for c in s)


def new_p(ref_p, text, para_pr=None, char=None, style=None):
    """ref_p 의 문단 속성·첫 run 서식을 따르는 새 문단."""
    p = etree.Element(HP + 'p')
    p.set('id', '2147483648')
    p.set('paraPrIDRef', para_pr or ref_p.get('paraPrIDRef', '0'))
    p.set('styleIDRef', style if style is not None else ref_p.get('styleIDRef', '0'))
    p.set('pageBreak', '0')
    p.set('columnBreak', '0')
    p.set('merged', '0')
    r0 = ref_p.find(HP + 'run')
    run = etree.SubElement(p, HP + 'run')
    run.set('charPrIDRef', char or (r0.get('charPrIDRef') if r0 is not None else '0'))
    t = etree.SubElement(run, HP + 't')
    t.text = text
    return p


def set_text_keep(p, new):
    """문단의 글을 new 로 바꾸되, 바뀌지 않은 낱말의 글자 모양(굵기·색 등)은 그대로 두고
    새로 들어가는 글은 이웃한 글자의 모양을 따른다(서식 문서의 일부 낱말만 고칠 때)."""
    import difflib
    nodes = []
    for r in p.findall(HP + 'run'):
        for t in r.findall(HP + 't'):
            if len(t):                     # 탭·줄바꿈 같은 자식 요소가 있으면 단순 교체
                set_text(p, new)
                return
            nodes.append(t)
    old = ''.join(t.text or '' for t in nodes)
    if not nodes or not old.strip():
        set_text(p, new)
        return
    owner = []
    for i, t in enumerate(nodes):
        owner += [i] * len(t.text or '')
    got = [[] for _ in nodes]
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    last = owner[0]
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                got[owner[i1 + k]].append(new[j1 + k])
            last = owner[i2 - 1]
        elif tag == 'replace':
            got[owner[i1]].append(new[j1:j2])
            last = owner[i1]
        elif tag == 'insert':
            got[owner[i1 - 1] if i1 > 0 else owner[0]].append(new[j1:j2])
    for t, parts in zip(nodes, got):
        t.text = ''.join(parts)


def _node_look(head, t):
    r = t.getparent()
    c = head.char.get(r.get('charPrIDRef'), {}) if r is not None else {}
    return (c.get('height'), c.get('color'), c.get('bold'), c.get('italic'))


def _anchor(old, nxt):
    a = old.rstrip()[-1:]
    if a and not a.isalnum():
        return ('after', a)
    b = nxt.lstrip()[:1]
    if b and not b.isalnum():
        return ('before', b)
    return None


def transfer_pieces(olds, new):
    """서식 문단의 글자 덩어리(굵은 앞말 + 보통 글 등)가 나뉜 자리(쌍점·기호)를 새 글에서 찾아 같은 수로 나눈다. 못 찾으면 None."""
    pieces, pos = [], 0
    for i in range(len(olds) - 1):
        if i == 0 and bullet_marker(olds[0] + 'x') == olds[0] and new.startswith(olds[0]):
            pieces.append(olds[0])
            pos = len(olds[0])
            continue
        an = _anchor(olds[i], olds[i + 1])
        if an is None:
            return None
        kind, ch = an
        if kind == 'after':
            j = new.find(ch, pos)
            if j < 0:
                return None
            end = j + 1
            while end < len(new) and new[end] == ' ':
                end += 1
        else:
            j = new.find(ch, pos + 1)
            if j < 0:
                return None
            end = j
        if end <= pos or end >= len(new):
            return None
        pieces.append(new[pos:end])
        pos = end
    pieces.append(new[pos:])
    return pieces if all(pc for pc in pieces) else None


def fill_runs(p, full, head):
    """문단 p 의 글을 full 로. 서식 문단이 '굵은 앞말 + 보통 글'처럼 여러 글자 덩어리였으면 같은 자리에서 나눠 모양을 따르고,
    못 나누면 글자가 가장 많은 덩어리(본문 모양)에 통째로 넣는다. 글머리 기호 덩어리는 그대로 둔다."""
    ts = own_ts(p)
    ne = [t for t in ts if ''.join(t.itertext()).strip()]
    if len(ne) < 2:
        set_text(p, full)
        return
    if '**' not in full and len({_node_look(head, t) for t in ne}) >= 2:
        pieces = transfer_pieces([''.join(t.itertext()) for t in ne], full)
        if pieces:
            for t, pc in zip(ne, pieces):
                _set_t(t, pc)
            for t in ts:
                if t not in ne:
                    _set_t(t, '')
            return
    first = ''.join(ne[0].itertext())
    rest = ne
    keep_first = False
    if bullet_marker(first + 'x') == first and full.startswith(first):
        keep_first = True
        full = full[len(first):]
        rest = ne[1:]
    body = max(rest, key=lambda t: len(''.join(t.itertext())))
    for t in ts:
        if keep_first and t is ne[0]:
            continue
        _set_t(t, full if t is body else '')


def para_kind(text):
    """문단 앞머리 종류: 글머리 기호(기호 글자) · 번호(종류 번호) · 일반."""
    mk = bullet_marker(text or '')
    if mk:
        return ('b', mk.strip())
    for i, pat in enumerate(Kit.NUM_CLASSES):
        if re.match(pat, text or ''):
            return ('n', i)
    return ('p', '')


def match_proto(protos, line):
    """서식 칸(박스)의 문단들 중 새 줄과 같은 종류(기호·번호·일반)의 문단을 고른다."""
    if len(protos) == 1:
        return protos[0]
    want = para_kind(line)
    kinds = [para_kind(ptext(q)) for q in protos]
    for q, k in zip(protos, kinds):
        if k == want:
            return q
    if want[0] != 'p':                       # 같은 기호가 없으면 같은 계열(기호/번호) 중 첫 것
        for q, k in zip(protos, kinds):
            if k[0] == want[0]:
                return q
    plain = [q for q, k in zip(protos, kinds) if k[0] == 'p']
    if plain:
        return plain[-1] if len(plain) > 1 and want[0] == 'p' else plain[0]
    return protos[0]


INLINE_BOLD = re.compile(r'\*\*(.+?)\*\*', re.S)


# ---------------------------------------------------------------- 서식 키트
class Kit:
    """서식에서 '어떤 역할에 어떤 모양의 견본을 쓸지'를 배운다.

    - 견본은 '처음 나온 것'이 아니라 '본문에서 가장 흔한 것'(표지 제외)을 쓴다.
    - 글머리 단계·번호 종류·소제목 종류·표 모양은 글 내용(기호·열 수)에 맞는 견본을 고른다.
    - 블록 사이 빈 줄은 서식에서 관찰한 '앞 역할 → 뒤 역할' 간격을 따른다.
    """

    NUM_CLASSES = [r'^\s*\d{1,2}\s*\.', r'^\s*[가-힣]\s*\.', r'^\s*\d{1,2}\s*\)', r'^\s*[가-힣]\s*\)',
                   r'^\s*\(\d{1,2}\)', r'^\s*\([가-힣]\)', r'^\s*[①-⑳]', r'^\s*[㉮-㉻]']

    def __init__(self, bp: Blueprint):
        self.bp = bp
        self.head = bp.head
        self.unknown_classes = set()
        self.by_role = {}
        for b in bp.blocks:
            self.by_role.setdefault(b.role, []).append(b)
        self._learn_bullets()
        self._learn_headings()
        self._learn_tables()
        self._learn_gaps()
        self.text_width = min(bp.page['text_width'] - 400, 47900) if bp.page['text_width'] > 0 else 47000
        if self.table_default is not None:
            self.text_width = int(self.table_default.info['tbl'].find(HP + 'sz').get('width'))

    # ---- 견본 고르기 -------------------------------------------------------
    def body(self, role):
        """역할별 블록(표지 제외). 본문에 없으면 전체."""
        lst = self.by_role.get(role, [])
        bodies = [b for b in lst if not b.info.get('cover')]
        return bodies or lst

    def simplest(self, blocks):
        """같은 모양 묶음에서 대표 블록: 바깥 문단 모양이 가장 흔한 것 중, 글자 덩어리가 가장 적은(=구조가 단순한) 것."""
        st = self.bp.styles
        if st is not None and len(blocks) > 2:
            from .analyze import _para_look
            cnt = Counter(_para_look(st, b.info['para_pr']) for b in blocks)
            top = cnt.most_common(1)[0][0]
            blocks = [b for b in blocks if _para_look(st, b.info['para_pr']) == top]
        return min(blocks, key=lambda b: (b.info.get('nruns', 1) or 9, b.idx))

    def mode_rep(self, blocks):
        if not blocks:
            return None
        groups = {}
        for b in blocks:
            groups.setdefault(b.cls, []).append(b)
        best = max(groups.values(), key=lambda g: (len(g), -g[0].idx))
        return self.simplest(best)

    def by_class(self, cid):
        info = self.bp.classes.get(cid)
        if not info:
            self.unknown_classes.add(cid)
            return None
        return self.simplest([self.bp.blocks[i] for i in info['blocks']])

    # ---- 글머리 단계
    def _learn_bullets(self):
        groups = {}
        for b in self.body('bullet'):
            key = (b.info.get('marker', '').strip(), b.info.get('left', 0))
            groups.setdefault(key, []).append(b)
        self._bullet_keys = []
        levels = []
        for key, lst in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[1][0].idx)):
            levels.append(self.mode_rep(lst))
            self._bullet_keys.append(key)
        self.bullet_levels = levels

    def bullet_level_of(self, b):
        key = (b.info.get('marker', '').strip(), b.info.get('left', 0))
        if key in self._bullet_keys:
            return self._bullet_keys.index(key) + 1
        return 1

    def num_class(self, text):
        for i, pat in enumerate(self.NUM_CLASSES):
            if re.match(pat, text or ''):
                return i
        return None

    def numbered_proto(self, text):
        lst = self.body('numbered')
        if not lst:
            return None
        cls = {}
        for b in lst:
            c = self.num_class(b.text)
            if c is not None:
                cls.setdefault(c, []).append(b)
        want = self.num_class(text)
        if want in cls:
            return self.mode_rep(cls[want])
        if not cls:
            return self.mode_rep(lst)
        ordered = sorted(cls.items(), key=lambda kv: (self.head.para.get(kv[1][0].info['para_pr'], {}).get('left', 0), kv[0]))
        depth = min(want if want is not None else 0, len(ordered) - 1)
        return self.mode_rep(ordered[depth][1])

    def numbered_extra(self, text):
        """서식에 없는 더 깊은 번호 단계(예: 1) 가) )는 마지막 단계에서 몇 단계 더 들여쓸지."""
        lst = self.body('numbered')
        cls = {self.num_class(b.text) for b in lst if self.num_class(b.text) is not None}
        want = self.num_class(text)
        if want is None or want in cls or not cls:
            return 0
        return max(0, min(want, 5) - (len(cls) - 1))

    # ---- 소제목 종류
    def _learn_headings(self):
        self.heading_groups = {}
        allh = self.body('heading') + self.body('heading_text')
        for b in allh:
            first = b.text.split(' | ')[0]
            self.heading_groups.setdefault(heading_class(first), []).append(b)
        self.heading_default = self.mode_rep(allh) if allh else None

    def heading_proto(self, text):
        cls = heading_class(text)
        if cls in self.heading_groups:
            return self.mode_rep(self.heading_groups[cls])
        return self.heading_default

    def proto(self, role, level=1, text=None, cls=None):
        if cls:
            b = self.by_class(cls)
            if b is not None:
                return b
        if role == 'numbered':
            return self.numbered_proto(text)
        if role == 'bullet':
            if not self.bullet_levels:
                return None
            return self.bullet_levels[min(level, len(self.bullet_levels)) - 1]
        if role == 'table' and getattr(self, 'table_default', None) is not None:
            return self.table_default
        if role == 'heading':
            h = self.heading_proto(text or '')
            if h is not None:
                return h
        if role == 'paragraph':
            plain = [b for b in self.body('paragraph') if b.info.get('font', 0) <= self.bp.body_size + 100]
            return self.mode_rep(plain or self.body('paragraph'))
        lst = self.body(role)
        return self.mode_rep(lst) if lst else None

    # ---- 블록 사이 간격 학습: '앞 역할 → 뒤 역할' 사이에 서식이 둔 빈 줄
    def role_key(self, b):
        if b.role == 'bullet':
            return f'bullet{self.bullet_level_of(b)}'
        if b.role == 'heading_text':
            return 'heading'
        if b.info.get('cover'):
            return 'cover'
        return b.role

    def _learn_gaps(self):
        blocks = self.bp.blocks
        pair = {}
        first = {}
        vis = [b for b in blocks if b.role != 'blank']
        for k in range(len(vis) - 1):
            a, c = vis[k], vis[k + 1]
            blanks = [x for x in blocks[a.idx + 1:c.idx] if x.role == 'blank']
            if c.idx - a.idx - 1 != len(blanks):
                continue
            sig = tuple((x.info['para_pr'], x.info['style']) for x in blanks[:3])
            ka, kb = self.role_key(a), self.role_key(c)
            pair.setdefault((ka, kb), {}).setdefault(sig, []).append(tuple(blanks[:3]))
            first.setdefault(ka, {}).setdefault(sig, []).append(tuple(blanks[:3]))
        self._gap_pair = pair
        self._gap_first = first
        blanks = self.by_role.get('blank', [])
        self.default_blank = blanks[0] if blanks else None

    def gap(self, prev_key, next_key):
        """prev→next 사이에 넣을 빈 줄 블록 목록(없으면 빈 목록)."""
        for table, key in ((self._gap_pair, (prev_key, next_key)), (self._gap_first, prev_key)):
            obs = table.get(key)
            if obs:
                best = max(obs.values(), key=len)
                return list(best[0])
        return []

    def blank_el(self, blk=None):
        b = blk or self.default_blank
        if b is None:
            p = etree.Element(HP + 'p', id='0', paraPrIDRef='0', styleIDRef='0', pageBreak='0', columnBreak='0',
                              merged='0')
            etree.SubElement(p, HP + 'run', charPrIDRef='0')
            return p
        el = copy.deepcopy(b.el)
        strip_ls(el)
        return el

    # ---- 표 서식 학습
    @staticmethod
    def _mid_cell(lst):
        """같은 종류 칸들 중 가운데 줄의 것(맨 위·맨 아래 줄의 굵은 테두리 영향을 피함)."""
        rs = sorted(c['r'] for c in lst)
        med = rs[len(rs) // 2]
        return min(lst, key=lambda c: (abs(c['r'] - med), c['r']))

    def _learn_one(self, tb):
        cells, cols, rows = tb.info['cells'], tb.info['cols'], tb.info['rows']
        hdr_rows = 0
        for r in range(rows):
            rc = [c for c in cells if c['r'] == r]
            if rc and all(c['filled'] for c in rc):
                hdr_rows += 1
            else:
                break
        if hdr_rows >= rows:
            hdr_rows = 1 if rows > 1 else 0
        tb.info['hdr_rows'] = hdr_rows
        lists = {}
        for c in cells:
            zone = 'head' if c['r'] < hdr_rows else 'body'
            if c['cs'] >= cols:
                ck = 'full'
            elif c['c'] == 0:
                ck = 'first'
            elif c['c'] + c['cs'] >= cols:
                ck = 'last'
            else:
                ck = 'mid'
            if (c['rs'] > 1 or c['cs'] > 1) and zone != 'head':
                continue
            lists.setdefault((zone, ck), []).append(c)
        cls = {k: (v[0] if k[0] == 'head' else self._mid_cell(v)) for k, v in lists.items()}
        bycol = {}
        for c in cells:
            if c['cs'] == 1 and c['rs'] == 1:
                bycol.setdefault(('head' if c['r'] < hdr_rows else 'body', c['c']), []).append(c)
        bycol = {k: (v[0] if k[0] == 'head' else self._mid_cell(v)) for k, v in bycol.items()}
        if hdr_rows == 0 and ('body', 'first') in cls:       # 머리 줄이 없는 표(라벨 칸 + 내용 칸): 머리 = 라벨 칸 모양
            for ck in ('first', 'mid', 'last', 'full'):
                cls[('head', ck)] = cls[('body', 'first')]
        body, bodies, heads = {}, [], []
        for k, c in cls.items():
            if k[0] == 'body':
                al = self.head.para.get(c['para_pr'], {}).get('align', 'JUSTIFY')
                body.setdefault('c' if al == 'CENTER' else 'l', (c['para_pr'], c['char'], c['style']))
        for c in cells:
            if c['r'] < hdr_rows:
                heads.append(c['h'])
            else:
                bodies.append(c['h'])
        # 열 너비(한 칸짜리 셀에서)
        colw = [0] * cols
        for c in cells:
            if c['cs'] == 1 and c['c'] < cols:
                colw[c['c']] = max(colw[c['c']], c['w'])
        if not all(colw):
            colw = None
        # 가장자리(테두리) 모형
        votes = {}
        for c in cells:
            bd = self.head.borders.get(str(c['bf']))
            if not bd:
                continue
            zone = 'head' if c['r'] < hdr_rows else 'body'
            r0, r1, c0, c1 = c['r'], c['r'] + c['rs'], c['c'], c['c'] + c['cs']
            for key, val in ((('v', vkey(c0, cols), zone), bd['left']), (('v', vkey(c1, cols), zone), bd['right']),
                             (('h', hkey(r0, rows, hdr_rows), ccls(c0, c['cs'], cols)), bd['top']),
                             (('h', hkey(r1, rows, hdr_rows), ccls(c0, c['cs'], cols)), bd['bottom'])):
                votes.setdefault(key, Counter())[val] += 1
        edges = {k: v.most_common(1)[0][0] for k, v in votes.items()}
        grid = {(c['r'], c['c']): c for c in cells}
        return {'cls': cls, 'bycol': bycol, 'cols': cols, 'rows': rows, 'grid': grid, 'body': body, 'head_h': min(heads) if heads else None, 'hdr_rows': hdr_rows,
                'body_h': min(bodies) if bodies else None, 'colw': colw, 'edges': edges,
                'width': int(tb.info['tbl'].find(HP + 'sz').get('width'))}

    @staticmethod
    def _pick(cls, rk, ck):
        order_col = {'first': ['first', 'mid', 'last', 'full'], 'mid': ['mid', 'last', 'first', 'full'],
                     'last': ['last', 'mid', 'first', 'full'], 'full': ['full', 'first', 'mid', 'last']}[ck]
        order_row = ['head', 'body'] if rk == 'head' else ['body', 'head']
        for r in order_row:
            for c in order_col:
                if (r, c) in cls:
                    return cls[(r, c)]
        return None

    def _learn_tables(self):
        self.tables = self.by_role.get('table', [])
        self.table_kits = {}
        for tb in self.by_role.get('table', []) + self.by_role.get('heading', []) + self.by_role.get('box', []):
            if tb.info.get('tbl') is not None:
                self.table_kits[tb.idx] = self._learn_one(tb)
        # 자료 표 후보: 본문의 표(표지 제외), 사진 칸 표 제외, 12열 이하
        self.data_tables = [tb for tb in self.body('table')
                            if tb.info['cols'] <= 12 and not tb.info.get('has_pic') and tb.info['rows'] >= 1]
        self.table_default = None
        self.cls = {}
        self.body_cells = {}
        heads, bodies = [], []
        if self.data_tables:
            self.table_default = self.choose_table(ncols=None)
        elif self.tables:
            self.table_default = self.tables[0]
        if self.table_default is not None:
            one = self.table_kits[self.table_default.idx]
            self.cls = dict(one['cls'])
            self.body_cells = dict(one['body'])
        else:
            self.body_cells = {}
        for tb in self.data_tables:
            one = self.table_kits[tb.idx]
            if one['head_h']:
                heads.append(one['head_h'])
            if one['body_h']:
                bodies.append(one['body_h'])
        self.head_h = min(heads) if heads else 2148
        self.body_h = min(bodies) if bodies else 2000

    def choose_table(self, ncols=None, want_header=True, cls=None):
        """새 표에 모양을 빌려줄 기존 표: 열 수가 같은 것을 우선하고, 같은 설계는 본문에서 더 흔한 것."""
        if cls:
            b = self.by_class(cls)
            if b is not None:
                return b
        cands = self.data_tables or self.tables
        if not cands:
            return None
        freq = Counter(b.cls for b in cands)

        def score(b):
            s = 0.0
            if ncols is not None:
                s -= 12 * abs(b.info['cols'] - ncols)
                if b.info['cols'] == ncols:
                    s += 40
            s += min(freq[b.cls], 8)
            s += 6 if b.info.get('fills', 0) > 0 else 0          # 머리칸 색이 있는 표
            s += 3 if b.info['rows'] >= 3 else 0
            s -= 0.05 * abs(b.info['rows'] - 4)
            return s - b.idx * 1e-4
        best = max(cands, key=score)
        same = [b for b in cands if b.cls == best.cls]
        return max(same, key=lambda b: (b.info['rows'] >= 2, b.info['rows'] <= 12, -abs(b.info['rows'] - 5), -b.idx))

    def cell_rec(self, rk, ck):
        return self._pick(self.cls, rk, ck)

    def table_kit(self, idx=None):
        return TableKit(self, self.table_kits.get(int(idx)) if idx is not None else None)


class TableKit:
    """표 하나를 만들 때 쓰는 서식 묶음: 지정한 표(proto)의 서식을 우선, 없으면 전역 서식."""

    def __init__(self, kit, own):
        self.kit, self.own = kit, own
        self.body = dict(kit.body_cells)
        if own:
            self.body.update(own['body'])
        self.head_h = (own or {}).get('head_h') or kit.head_h
        self.body_h = (own or {}).get('body_h') or kit.body_h

    def cell_rec(self, rk, ck, col=None):
        if self.own:
            if col is not None and (rk, col) in self.own.get('bycol', {}):
                return self.own['bycol'][(rk, col)]
            r = self.kit._pick(self.own['cls'], rk, ck)
            if r is not None:
                return r
        return self.kit.cell_rec(rk, ck)

    def cell_at(self, r, c, cs, rs, nrows, ncols, nh):
        """prototype 표와 열 수가 같을 때, 같은 자리(줄 번호는 앞쪽은 그대로, 뒤쪽은 가운데 줄)의 칸 모양."""
        own = self.own
        if not own or own.get('cols') != ncols:
            return None
        hdr, prow = own['hdr_rows'], own['rows']
        if r < nh:
            if not hdr:
                return None
            pr_ = min(r, hdr - 1)
        else:
            k = r - nh
            body_rows = prow - hdr
            if body_rows <= 0:
                return None
            if nrows == prow and nh == hdr:
                pr_ = r
            elif k < body_rows - 1:
                pr_ = hdr + k
            else:
                pr_ = hdr + max(body_rows - 2, 0)
        cell = own['grid'].get((pr_, c))
        if cell and cell['cs'] == cs and cell['rs'] == rs:
            return cell
        return None

    def edge(self, orient, key, zone):
        """prototype 표에서 배운 테두리(종류, 굵기, 색). 배운 것이 없으면 None(= 칸의 원래 테두리 유지)."""
        if not self.own or not self.own.get('edges'):
            return None
        ed = self.own['edges']
        if orient == 'v':
            for k in V_FALL[key]:
                for z in (zone, 'body' if zone == 'head' else 'head'):
                    if ('v', k, z) in ed:
                        return ed[('v', k, z)]
            return None
        cc_order = [zone] + [x for x in ('mid', 'first', 'last', 'full') if x != zone]
        for k in H_FALL[key]:
            for cc in cc_order:
                if ('h', k, cc) in ed:
                    return ed[('h', k, cc)]
        if key in ('h_mid', 'h_headmid', 'h_headbottom'):       # 줄 사이 선을 못 배웠으면 안쪽 세로선과 같은 모양
            for k in ('v_mid', 'v_first', 'v_last'):
                for z in (zone or 'body', 'body', 'head'):
                    if ('v', k, z) in ed:
                        return ed[('v', k, z)]
        return None


# ---------------------------------------------------------------- 빌더
class Builder:
    def __init__(self, template: str, base_dir: str = None):
        self.bp = analyze(template)
        self.kit = Kit(self.bp)
        self.pkg = self.bp.pkg
        self.head = self.bp.head
        self._para_cache = {}
        self._tbl_id = 1000000000
        self.warnings = []
        self._compact = 0
        self.base_dir = base_dir
        self._imgs = {}
        self._img_new = []
        self._img_idx = next_image_index(self.pkg)
        self._uid = 0

    # ---- 문단 정렬 변형 생성(header.xml 에 paraPr 추가)
    def ensure_para(self, pid, align):
        key = (pid, align)
        if key in self._para_cache:
            return self._para_cache[key]
        cur = self.head.para.get(pid, {}).get('align')
        if cur == align or (align == 'LEFT' and cur == 'JUSTIFY'):
            return pid
        root = self.head.root
        src = None
        maxid = 0
        for pp in root.iter(HH + 'paraPr'):
            maxid = max(maxid, int(pp.get('id')))
            if pp.get('id') == pid:
                src = pp
        if src is None:
            return pid
        new = copy.deepcopy(src)
        nid = str(maxid + 1)
        new.set('id', nid)
        new.find(HH + 'align').set('horizontal', align)
        src.getparent().append(new)
        lst = src.getparent()
        lst.set('itemCnt', str(len(lst)))
        self.head.para[nid] = dict(self.head.para.get(pid, {}), align=align)
        self._para_cache[key] = nid
        return nid

    def indented_para(self, pid, extra):
        key = ('ind', pid, extra)
        if key in self._para_cache:
            return self._para_cache[key]
        root = self.head.root
        src = None
        maxid = 0
        for pp in root.iter(HH + 'paraPr'):
            maxid = max(maxid, int(pp.get('id')))
            if pp.get('id') == pid:
                src = pp
        if src is None:
            return pid
        new = copy.deepcopy(src)
        nid = str(maxid + 1)
        new.set('id', nid)
        for el in new.iter('{%s}left' % NS['hc']):
            el.set('value', str(int(el.get('value')) + extra))
        lst = src.getparent()
        lst.append(new)
        lst.set('itemCnt', str(len(lst)))
        self.head.para[nid] = dict(self.head.para.get(pid, {}), left=self.head.para.get(pid, {}).get('left', 0) + extra)
        self._para_cache[key] = nid
        return nid

    def ensure_char(self, cid, bold=None):
        """글자 모양 cid 에서 굵기만 바꾼 글자 모양 번호(이미 같은 모양이 있으면 그것)."""
        key = ('char', str(cid), bold)
        if key in self._para_cache:
            return self._para_cache[key]
        root = self.head.root
        src = None
        maxid = 0
        for cp in root.iter(HH + 'charPr'):
            maxid = max(maxid, int(cp.get('id')))
            if cp.get('id') == str(cid):
                src = cp
        if src is None:
            return str(cid)
        new = copy.deepcopy(src)
        new.set('id', str(maxid + 1))
        b = new.find(HH + 'bold')
        if bold and b is None:
            b = etree.Element(HH + 'bold')
            ul = new.find(HH + 'underline')
            if ul is not None:
                ul.addprevious(b)
            else:
                new.append(b)
        elif bold is False and b is not None:
            new.remove(b)
        sig = re.sub(rb' id="\d+"', b'', etree.tostring(new))
        for cp in root.iter(HH + 'charPr'):
            if re.sub(rb' id="\d+"', b'', etree.tostring(cp)) == sig:
                self._para_cache[key] = cp.get('id')
                return cp.get('id')
        lst = src.getparent()
        lst.append(new)
        lst.set('itemCnt', str(len(lst)))
        self.head.char[new.get('id')] = dict(self.head.char.get(str(cid), {}), bold=bool(bold))
        self._para_cache[key] = new.get('id')
        return new.get('id')

    def _apply_inline(self, el):
        """본문 안의 **굵게** 표시를 글자 모양(굵게)으로 바꾼다."""
        for p in list(el.iter(HP + 'p')):
            for r in p.findall(HP + 'run'):
                ts = r.findall(HP + 't')
                if len(ts) != 1 or len(r) != 1 or len(ts[0]):
                    continue
                text = ts[0].text or ''
                if '**' not in text:
                    continue
                lead = ''
                if text.lstrip().startswith('*'):      # '**' 글머리 기호(서식의 글자)는 굵게 표시가 아니므로 건드리지 않는다
                    lead = bullet_marker(text + 'x')
                    if lead and '**' not in text[len(lead):]:
                        continue
                    text = text[len(lead):]
                if text.count('**') % 2:
                    ts[0].text = lead + text.replace('**', '')
                    continue
                segs, pos = [], 0
                for m in INLINE_BOLD.finditer(text):
                    if m.start() > pos:
                        segs.append((text[pos:m.start()], False))
                    segs.append((m.group(1), True))
                    pos = m.end()
                if pos < len(text):
                    segs.append((text[pos:], False))
                if lead:
                    segs.insert(0, (lead, False))
                segs = [(t, b) for t, b in segs if t != '']
                if not segs:
                    continue
                base = r.get('charPrIDRef')
                prev = r
                for i, (t, b) in enumerate(segs):
                    if i == 0:
                        run = r
                    else:
                        run = copy.deepcopy(r)
                        prev.addnext(run)
                    run.find(HP + 't').text = t
                    run.set('charPrIDRef', self.ensure_char(base, True) if b else base)
                    prev = run

    def _fill(self, p, text, marker=None, bullet=False):
        """문단 p 에 글 넣기(글머리 기호·굵은 앞말 같은 서식 문단의 글자 덩어리 구성을 따름)."""
        if bullet:
            ts = own_ts(p)
            # 기호만 따로 한 덩어리('* ')인 서식도 있으므로 뒤에 글자를 붙여 판별한다
            k = next((i for i, t in enumerate(ts) if is_bullet_start(''.join(t.itertext()) + 'x')), None)
            if k is None:
                fill_runs(p, (marker or '') + text, self.head)
                return
            cur = ''.join(ts[k].itertext())
            mk = bullet_marker(cur + 'x') if marker is None else marker
            fill_runs(p, mk + text, self.head)
        else:
            fill_runs(p, text, self.head)

    def ensure_borderfill(self, base_id, left, right, top, bottom):
        """base 칸의 채우기(색)는 그대로 두고 네 테두리만 바꾼 borderFill 을 (없으면 만들어) 돌려준다."""
        want = (left, right, top, bottom)
        if all(w is None for w in want):
            return base_id
        key = ('bf', str(base_id), want)
        if key in self._para_cache:
            return self._para_cache[key]
        root = self.head.root
        src = None
        maxid = 0
        for bf in root.iter(HH + 'borderFill'):
            maxid = max(maxid, int(bf.get('id')))
            if bf.get('id') == str(base_id):
                src = bf
        if src is None:
            return base_id
        new = copy.deepcopy(src)
        new.set('id', str(maxid + 1))
        for tag, val in (('leftBorder', left), ('rightBorder', right), ('topBorder', top), ('bottomBorder', bottom)):
            if val is None:
                continue
            el = new.find(HH + tag)
            if el is not None:
                el.set('type', val[0])
                el.set('width', val[1])
                el.set('color', val[2])
        # 같은 모양이 이미 있으면 그것을 재사용
        sig = etree.tostring(new)
        sig_norm = re.sub(rb' id="\d+"', b'', sig)
        for bf in root.iter(HH + 'borderFill'):
            if re.sub(rb' id="\d+"', b'', etree.tostring(bf).replace(b' xmlns', b' xmlns')) == sig_norm:
                self._para_cache[key] = bf.get('id')
                return bf.get('id')
        lst = src.getparent()
        lst.append(new)
        lst.set('itemCnt', str(len(lst)))
        self.head.borders[new.get('id')] = dict(self.head.borders.get(str(base_id), {}),
                                                **{k: v for k, v in (('left', left), ('right', right), ('top', top), ('bottom', bottom)) if v is not None})
        self._para_cache[key] = new.get('id')
        return new.get('id')

    # ---- 개별 블록 생성 -------------------------------------------------
    def _clone(self, blk):
        el = copy.deepcopy(blk.el)
        strip_ls(el)
        # 쪽 번호 다시 시작(newNum)은 서식에서 그 블록이 처음 쓰일 때만 살린다(같은 모양을 여러 번 쓰면 쪽 번호가 매번 1로 돌아가므로)
        if el.find('.//' + HP + 'newNum') is not None:
            used = self.__dict__.setdefault('_newnum_used', set())
            if blk.idx in used:
                for nn in list(el.iter(HP + 'newNum')):
                    ctrl = nn.getparent()
                    if ctrl is not None and ctrl.tag == HP + 'ctrl' and len(ctrl) == 1:
                        ctrl.getparent().remove(ctrl)
                    elif ctrl is not None:
                        ctrl.remove(nn)
            else:
                used.add(blk.idx)
        return el

    # ---- 표지 -----------------------------------------------------------------
    def cover_slots(self, els):
        """표지 블록들 안에서 글이 있는 문단(문서 순서)."""
        return [p for el in els for p in el.iter(HP + 'p') if ptext(p).strip()]

    def _slot_size(self, p):
        for r in p.findall(HP + 'run'):
            if any(''.join(t.itertext()).strip() for t in r.findall(HP + 't')):
                return self.head.size(r.get('charPrIDRef'))
        return 0

    def make_cover(self, title, subtitle=None, fields=None):
        """서식의 표지 구간(맨 앞 ~ 본문 시작 전)을 통째로 복제해 제목·부제를 채운다.
        제목 = 표지에서 가장 큰 글자의 칸(같은 글이 여러 곳에 있으면 모두 바꿈). 나머지 칸은 fields 로 지정."""
        k = self.bp.cover_end
        if k <= 0:
            return None
        els = [self._clone(b) for b in self.bp.blocks[:k]]
        slots = self.cover_slots(els)
        if not slots:
            return els
        if fields:
            for i, p in enumerate(slots):
                set_text_keep(p, fields[i] if i < len(fields) else '')      # 바뀐 낱말만 새로, 나머지 글자 모양은 그대로
            if len(fields) != len(slots):
                self.warnings.append(f'표지에는 글 칸이 {len(slots)}개인데 fields 는 {len(fields)}개입니다(모자란 칸은 비움).')
        else:
            best = max(slots, key=lambda p: (self._slot_size(p), len(ptext(p))))
            old = ptext(best).strip()
            mapping = {old: title}
            sub_old = None
            if subtitle:
                # 부제 칸: 제목 칸 뒤쪽의 짧은 오른쪽/가운데 정렬 문단 중 마지막 것
                pos = slots.index(best)
                for p in reversed(slots[pos + 1:]):
                    al = self.head.para.get(p.get('paraPrIDRef'), {}).get('align')
                    t = ptext(p).strip()
                    if len(t) < 40 and al in ('RIGHT', 'CENTER') and t != old:
                        sub_old = t
                        break
                if sub_old:
                    mapping[sub_old] = subtitle
                else:
                    self.warnings.append('서식 표지에 부제(부서명 등)를 넣을 칸을 찾지 못해 무시했습니다.')
            for el in els:
                self._replace_text(el, mapping)
            rest = [ptext(p).strip() for p in self.cover_slots(els)
                    if ptext(p).strip() not in (title, subtitle or '') and ptext(p).strip() != '']
            rest = [r for r in rest if r not in (title, subtitle)]
            if rest:
                self.warnings.append('표지에 서식 원문의 다른 글이 그대로 남았습니다: ' + ', '.join(dict.fromkeys(x[:14] for x in rest[:8]))
                                     + ' → 바꾸려면 title 블록에 "fields":[…](글 칸 순서대로 %d개)를 쓰세요.' % len(slots))
        for el in els:
            self._renew_tables(el)
        return els

    def make_title(self, text, fields=None):
        """(표지 구간이 없는 서식용) 제목 한 줄."""
        for role in ('heading_text', 'paragraph'):
            el = self.make_simple(role, text)
            if el is not None:
                return el
        return None

    # ---- 글 채우기 ---------------------------------------------------------
    NUMTITLE = re.compile(r'^\s*([%s]+|\d{1,2}|[가-힣]|[IVX]+|[■◆□●○▶▷◈※▣])\s*[\.\)]?\s*(.*)$' % ROMAN_CHARS, re.S)

    def fill_heading_table(self, el, text):
        """표 모양 소제목: 번호 칸 + 제목 칸이면 나눠 채우고, 칸이 하나면 통째로."""
        ps = [p for p in el.iter(HP + 'p') if p is not el and ptext(p).strip()]
        if not ps:
            ps = [p for p in el.iter(HP + 'p') if p is not el][:1]
            if ps:
                set_text(ps[0], text)
            return
        if len(ps) == 1:
            set_heading_text(ps[0], text)
            return
        orig_first = ptext(ps[0]).strip()
        m = self.NUMTITLE.match(text)
        if m and m.group(2).strip() and (m.group(1) != text.strip()):
            num, title = m.group(1), m.group(2).strip()
            if orig_first[-1:] in '.)' and len(orig_first) > 1:
                num += orig_first[-1]
            set_text(ps[0], num)
            set_text(ps[1], title)
        else:
            if not bullet_marker(orig_first + ' x') and not orig_first.endswith(('.', ')')) and len(orig_first) <= 3:
                set_text(ps[0], '')
            set_text(ps[1], text.strip())
        for p in ps[2:]:
            set_text(p, '')

    def make_simple(self, role, text, level=1, cls=None):
        pr = self.kit.proto(role, level, text, cls)
        if pr is None:
            return None
        el = self._clone(pr)
        if pr.info.get('tbl') is not None:      # 표형(소제목 등)
            if role in ('heading', 'heading_text') or pr.role == 'heading':
                self.fill_heading_table(el, text)
            else:
                target = next((p for p in el.iter(HP + 'p') if p is not el and ptext(p).strip()), None)
                if target is None:
                    target = next((p for p in el.iter(HP + 'p') if p is not el), None)
                if target is not None:
                    set_text(target, text)
            self._renew_tables(el)
        else:
            if role == 'numbered':
                ex = self.kit.numbered_extra(text)
                if ex:
                    el.set('paraPrIDRef', self.indented_para(el.get('paraPrIDRef'), 1300 * ex))
            if role == 'bullet' or pr.role == 'bullet':
                if pr.info.get('marker', None) == '':
                    self._fill(el, text)          # 글머리를 문단 모양이 자동으로 붙이는 서식
                else:
                    self._fill(el, text, bullet=True)
            elif role in ('heading_text', 'heading') or pr.role == 'heading_text':
                set_heading_text(el, text)
            else:
                self._fill(el, text)
        return el

    def _first(self, *cands):
        for cand in cands:
            role, text = cand[0], cand[1]
            el = self.make_simple(role, text)
            if el is not None:
                return el
        return None

    def make_box(self, lines, title=None, cls=None):
        pr = self.kit.proto('box', cls=cls)
        if pr is None:
            return None
        el = self._clone(pr)
        sub = el.find('.//' + HP + 'subList')
        ps = sub.findall(HP + 'p')
        head_p = ps[0]
        body_p = ps[1] if len(ps) > 1 else ps[0]
        for q in ps:
            sub.remove(q)
        seq = ([(title, head_p)] if title else []) + [(ln, None) for ln in lines]
        if not seq:                      # 글이 없는 박스도 빈 문단 하나는 남긴다(한글이 빈 칸을 열지 못함)
            seq = [('', body_p)]
        body_ps = ps[1:] if len(ps) > 1 and (title or ps[0] is not body_p) else ps
        body_ps = [q for q in (ps[1:] if len(ps) > 1 else ps)] or ps
        for text, proto in seq:
            base = proto if proto is not None else match_proto(body_ps, text)
            q = copy.deepcopy(base)
            strip_ls(q)
            fill_runs(q, text, self.head)
            sub.append(q)
        # 높이 추정
        tbl = el.find('.//' + HP + 'tbl')
        w = int(tbl.find(HP + 'sz').get('width')) - 1300
        size = 1050
        r0 = body_p.find(HP + 'run')
        if r0 is not None:
            size = self.head.size(r0.get('charPrIDRef'))
        n = 0
        for text, _ in seq:
            n += max(1, math.ceil(dwidth(text) / max(8, w / (size * 0.94))))
        h = int(n * size * 1.25 + 700)
        tbl.find(HP + 'sz').set('height', str(h))
        for c in tbl.iter(HP + 'cellSz'):
            c.set('height', str(h))
        self._renew_tables(el)
        return el

    # ---- 표 ---------------------------------------------------------------
    IMG_MD = re.compile(r'^!\[(.*?)\]\((.+?)\)$')

    @classmethod
    def _norm_cell(cls, c):
        if isinstance(c, dict):
            text = c.get('text', '')
            lines = text if isinstance(text, list) else str(text).split(chr(10))
            return {'lines': lines or [''], 'cs': int(c.get('colspan', 1)), 'rs': int(c.get('rowspan', 1)),
                    'align': c.get('align'), 'image': c.get('image'), 'width_mm': c.get('width_mm'),
                    'max_h_mm': c.get('max_h_mm', 70)}
        if isinstance(c, list):
            return {'lines': [str(x) for x in c], 'cs': 1, 'rs': 1, 'align': None}
        s = str(c) if c is not None else ''
        m = cls.IMG_MD.match(s.strip())
        if m:
            return {'lines': [m.group(1)] if m.group(1) else [''], 'cs': 1, 'rs': 1, 'align': 'c',
                    'image': m.group(2), 'width_mm': None, 'max_h_mm': 70}
        return {'lines': s.split(chr(10)), 'cs': 1, 'rs': 1, 'align': None}

    # ---- 사진 --------------------------------------------------------------
    def resolve_path(self, p):
        if os.path.isabs(p) and os.path.exists(p):
            return p
        tried = []
        for base in (self.base_dir, os.getcwd()):
            if base:
                q = os.path.join(base, p)
                tried.append(q)
                if os.path.exists(q):
                    return q
        raise ImageError('사진 파일을 찾을 수 없습니다: ' + p + ' (찾아본 곳: ' + ', '.join(tried) + ')')

    def add_image(self, path, max_w, max_h, want_w=None):
        full = os.path.abspath(self.resolve_path(path))
        if full not in self._imgs:
            # 표시 칸 크기에 맞춰 픽셀을 줄이고 사진은 JPEG·도표는 팔레트 PNG 로(문서 용량이 그림 때문에 커지지 않게)
            data, ext, wpx, hpx, _, _ = prepare_for_box(full, max_w, max_h, want_w)
            bin_id = f'image{self._img_idx}'
            self._img_idx += 1
            self._imgs[full] = (bin_id, ext, data, wpx, hpx)
            self._img_new.append((bin_id, ext, data))
        bin_id, ext, data, wpx, hpx = self._imgs[full]
        w, h = fit_size(wpx, hpx, max_w, max_h, want_w)
        self._uid += 1
        return {'bin_id': bin_id, 'w': w, 'h': h, 'wpx': wpx, 'hpx': hpx, 'uid': self._uid,
                'name': os.path.basename(full)}

    def _pic_run(self, char_id, info, inline=True):
        return pic_run(char_id, info['bin_id'], info['w'], info['h'], info['wpx'], info['hpx'], inline=inline,
                       uid=info['uid'], name=info['name'])

    def center_pair(self):
        kit = self.kit
        if 'c' in kit.body_cells:
            return kit.body_cells['c']
        if 'l' in kit.body_cells:
            pp, ch, st = kit.body_cells['l']
            return (self.ensure_para(pp, 'CENTER'), ch, st)
        for pid, inf in self.head.para.items():
            if inf.get('align') == 'CENTER':
                return (pid, '0', '0')
        return ('0', '0', '0')

    def make_image_block(self, spec):
        """단독 사진(+캡션). 반환: 문단 목록"""
        path = spec.get('path') or spec.get('image')
        if not path:
            raise BuildError('image 블록에 path 가 없습니다.')
        want = float(spec['width_mm']) * MM if spec.get('width_mm') else None
        info = self.add_image(path, self.kit.text_width - 200, int(float(spec.get('max_height_mm', 100)) * MM), want)
        pp, ch, st = self.center_pair()
        dummy = etree.Element(HP + 'p')
        p = new_p(dummy, '', para_pr=pp, char=ch, style=st)
        p.replace(p.find(HP + 'run'), self._pic_run(ch or '0', info))
        out = [p]
        if spec.get('caption'):
            out.append(new_p(dummy, spec['caption'], para_pr=pp, char=ch, style=st))
        return out

    def make_gallery(self, spec):
        """사진 대지: 표 안에 사진 격자(+캡션 줄)."""
        raw = spec.get('images') or []
        imgs = []
        for x in raw:
            if isinstance(x, str):
                imgs.append({'path': x, 'caption': ''})
            else:
                imgs.append({'path': x.get('path') or x.get('image'), 'caption': x.get('caption', '')})
        if not imgs:
            return None
        cols = int(spec.get('columns') or (3 if len(imgs) >= 3 else len(imgs)))
        rows = []
        for i in range(0, len(imgs), cols):
            chunk = imgs[i:i + cols]
            pad = [''] * (cols - len(chunk))
            rows.append([{'text': '', 'image': im['path'], 'width_mm': spec.get('width_mm'),
                          'max_h_mm': spec.get('max_height_mm', 60)} for im in chunk] + pad)
            if any(im['caption'] for im in chunk):
                rows.append([im['caption'] for im in chunk] + pad)
        header = [{'text': spec['title'], 'colspan': cols}] if spec.get('title') else []
        return self.make_table({'header': header, 'rows': rows, 'widths': [1] * cols, 'align': ['c'] * cols})

    def make_table(self, spec):
        kit0 = self.kit
        header = spec.get('header') or []
        rows = spec.get('rows') or []
        if header and not isinstance(header[0], list):
            hrows = [header]
        else:
            hrows = header
        hnorm = [[self._norm_cell(c) for c in r] for r in hrows]
        bnorm = [[self._norm_cell(c) for c in r] for r in rows]
        allrows = hnorm + bnorm
        if not allrows:
            return None
        # 격자 배치
        occ = set()
        placed = []            # (row, col, cell)
        ncols = 0
        for r, row in enumerate(allrows):
            c = 0
            for cell in row:
                while (r, c) in occ:
                    c += 1
                placed.append((r, c, cell))
                for rr in range(cell['rs']):
                    for cc in range(cell['cs']):
                        occ.add((r + rr, c + cc))
                c += cell['cs']
                ncols = max(ncols, c)
        nrows = len(allrows)
        if spec.get('proto') is not None:
            pr = self.bp.blocks[int(spec['proto'])]
            if pr.info.get('tbl') is None:
                raise BuildError(f'table.proto: {spec["proto"]}번 블록은 표가 아닙니다.')
            kit = kit0.table_kit(pr.idx)
            text_w = kit0.table_kits[pr.idx]['width']
        else:
            pr = kit0.choose_table(ncols=ncols, cls=spec.get('class') or spec.get('cls'))
            if pr is None:
                return None
            kit = kit0.table_kit(pr.idx)
            text_w = kit0.table_kits[pr.idx]['width']
        widths = spec.get('widths')
        proto_widths = False
        if not widths:
            cw = (kit0.table_kits[pr.idx].get('colw') if pr.info.get('tbl') is not None else None)
            proto_widths = bool(cw and len(cw) == ncols)
            widths = cw if proto_widths else [1] * ncols
        if len(widths) != ncols:
            widths = [1] * ncols
            self.warnings.append(f'표의 widths 개수가 열 수({ncols})와 달라 균등 분할했습니다.')
        total = spec.get('width') or text_w
        ws = [int(total * w / sum(widths)) for w in widths]
        ws[-1] += total - sum(ws)
        if not spec.get('widths') and not proto_widths:
            ws = self._fit_widths(ws, placed, len(hnorm))
        aligns = spec.get('align') or spec.get('aligns') or []
        aligns = [(a[0].lower() if a else None) for a in aligns]
        aligns += [None] * (ncols - len(aligns))
        nh = len(hnorm)
        min_row = spec.get('min_row')
        compact = self._compact

        # 표 껍데기 복제
        p = self._clone(pr)
        tbl_proto = pr.info['tbl']
        run = None
        for r_ in p.findall(HP + 'run'):
            if r_.find(HP + 'tbl') is not None:
                run = r_
                break
        tbl = run.find(HP + 'tbl')
        for tr in tbl.findall(HP + 'tr'):
            tbl.remove(tr)
        tbl.set('rowCnt', str(nrows))
        tbl.set('colCnt', str(ncols))
        trs = [etree.SubElement(tbl, HP + 'tr') for _ in range(nrows)]
        row_h = [0] * nrows
        cells_out = []
        for (r, c, cell) in placed:
            is_head = r < nh
            rk = 'head' if is_head else 'body'
            if cell['cs'] >= ncols:
                ck = 'full'
            elif c == 0:
                ck = 'first'
            elif c + cell['cs'] >= ncols:
                ck = 'last'
            else:
                ck = 'mid'
            same_cols = bool(kit.own) and kit.own.get('cols') == ncols
            exact = kit.cell_at(r, c, cell['cs'], cell['rs'], nrows, ncols, nh)
            rec = exact or kit.cell_rec(rk, ck, col=(c if (same_cols and cell['cs'] == 1) else None))
            if rec is None:
                return None
            w = sum(ws[c:c + cell['cs']])
            pp, ch, st = rec['para_pr'], rec['char'], rec['style']
            al = '' if is_head else (cell['align'] or aligns[c] or '')[:1].lower()
            tc = copy.deepcopy(rec['el'])
            same_shape = exact is not None and kit.own.get('rows') == nrows and kit.own.get('hdr_rows') == nh
            tc.set('borderFillIDRef', rec['bf'] if same_shape else self.ensure_borderfill(
                rec['bf'], kit.edge('v', vkey(c, ncols), 'head' if is_head else 'body'),
                kit.edge('v', vkey(c + cell['cs'], ncols), 'head' if is_head else 'body'),
                kit.edge('h', hkey(r, nrows, nh), ccls(c, cell['cs'], ncols)),
                kit.edge('h', hkey(r + cell['rs'], nrows, nh), ccls(c, cell['cs'], ncols))))
            sub = tc.find(HP + 'subList')
            protos = sub.findall(HP + 'p')
            ref_p = protos[0]
            for q in protos:
                sub.remove(q)
            img_h = 0
            if cell.get('image'):
                mar0 = tc.find(HP + 'cellMargin')
                max_w = w - int(mar0.get('left', '141')) - int(mar0.get('right', '141')) - 300
                want = int(float(cell['width_mm']) * MM) if cell.get('width_mm') else None
                info = self.add_image(cell['image'], max_w, int(float(cell.get('max_h_mm', 70)) * MM), want)
                ip = new_p(ref_p, '', para_pr=self.ensure_para(pp, 'CENTER'), char=ch, style=st)
                ip.replace(ip.find(HP + 'run'), self._pic_run(ch or '0', info))
                sub.append(ip)
                img_h = info['h']
            text_lines = [l for l in cell['lines'] if l != ''] if cell.get('image') else cell['lines']
            ch_for_size = ch
            for line in text_lines:
                q = match_proto(protos, line)
                np_ = copy.deepcopy(q)
                strip_ls(np_)
                fill_runs(np_, line, self.head)
                if al:
                    cur = self.head.para.get(np_.get('paraPrIDRef'), {}).get('align', 'JUSTIFY')
                    want_al = {'c': 'CENTER', 'r': 'RIGHT', 'l': 'LEFT'}.get(al, 'LEFT')
                    if cur != want_al and not (want_al == 'LEFT' and cur == 'JUSTIFY'):
                        np_.set('paraPrIDRef', self.ensure_para(np_.get('paraPrIDRef'), want_al))
                sub.append(np_)
                ch_for_size = first_char_id(np_) or ch
            tc.find(HP + 'cellAddr').set('colAddr', str(c))
            tc.find(HP + 'cellAddr').set('rowAddr', str(r))
            tc.find(HP + 'cellSpan').set('colSpan', str(cell['cs']))
            tc.find(HP + 'cellSpan').set('rowSpan', str(cell['rs']))
            size = self.head.size(ch_for_size or ch or '0', 1000)
            mar = tc.find(HP + 'cellMargin')
            inner = w - (int(mar.get('left', '141')) + int(mar.get('right', '141'))) - 200
            cpl = max(2, inner / (size * 0.94))
            nlines = sum(max(1, math.ceil(dwidth(l) / cpl)) for l in text_lines)
            base = kit.head_h if is_head else kit.body_h
            if exact is not None and cell['rs'] == 1:
                base = exact['h']
            if min_row and not is_head:
                base = min_row
            if compact >= 2 and not is_head:
                base = int(base * 0.8)
            if img_h:
                h = int(img_h + 500 + nlines * size * 1.2 + (250 if nlines else 0))
            else:
                h = int(base + (nlines - 1) * size * 1.15) if nlines > 1 else base
                if nlines > 1 and not is_head:
                    h = max(h, int(nlines * size * 1.2 + 700))
            tc.find(HP + 'cellSz').set('width', str(w))
            cs_h = h // cell['rs']
            row_h[r] = max(row_h[r], cs_h)
            cells_out.append((r, c, tc, cell))
        for (r, c, tc, cell) in sorted(cells_out, key=lambda x: (x[0], x[1])):
            tc.find(HP + 'cellSz').set('height', str(row_h[r] if cell['rs'] == 1 else row_h[r] * cell['rs']))
            trs[r].append(tc)
        tbl.find(HP + 'sz').set('width', str(total))
        tbl.find(HP + 'sz').set('height', str(sum(row_h)))
        page = self.bp.page
        usable = page['height'] - page['top'] - page['bottom']
        floating = spec.get('floating')
        if floating is None:
            pos0 = tbl_proto.find(HP + 'pos')
            proto_inline = pos0 is None or pos0.get('treatAsChar') == '1'
            # 서식의 표가 '글자처럼 취급'이면 그대로 두되, 쪽을 거의 채우는 큰 표만 떠 있게 한다(쪽 끝에서 잘림 방지)
            floating = sum(row_h) > (0.8 if proto_inline else 0.4) * usable
        if floating:
            tbl.find(HP + 'pos').set('treatAsChar', '0')
        elif spec.get('inline'):          # 서식의 표가 '떠 있는' 표일 때, 글자처럼 취급해 뒤따르는 글이 표 아래로 밀리게 한다
            tbl.find(HP + 'pos').set('treatAsChar', '1')
        self._renew_tables(p)
        return p

    def _fit_widths(self, ws, placed, nh):
        """줄바꿈되면 어색한 짧은 글(머리·숫자)이 들어가는 열이 너무 좁으면 넓은 열에서 덜어 온다."""
        n = len(ws)
        need = [0] * n
        for (r, c, cell) in placed:
            if cell['cs'] != 1:
                continue
            is_head = r < nh
            for line in cell['lines']:
                dw = dwidth(line)
                unit = dw if dw <= 9 else max((dwidth(t) for t in line.split()), default=dw)
                size = 1200 if not is_head else 1200
                need[c] = max(need[c], unit * size * 0.98 + 1000)
        ws = list(ws)
        orig_total = sum(ws)
        for _ in range(3):
            deficit = [(i, need[i] - ws[i]) for i in range(n) if need[i] > ws[i]]
            if not deficit:
                break
            total_def = sum(d for _, d in deficit)
            donors = [(i, ws[i] - need[i]) for i in range(n) if ws[i] - need[i] > 1500]
            spare = sum(d - 800 for _, d in donors if d > 800)
            if spare <= 0:
                break
            take = min(total_def, spare)
            for i, d in donors:
                if d > 800:
                    ws[i] -= int(take * (d - 800) / spare)
            for i, d in deficit:
                ws[i] += int(take * d / total_def)
        ws[-1] += orig_total - sum(ws)
        return ws

    def _renew_tables(self, el):
        for t in el.iter(HP + 'tbl'):
            self._tbl_id += 1
            t.set('id', str(self._tbl_id))

    # ---- clone(임의 블록 복제) ----------------------------------------
    def _other_blocks(self, section):
        """0번이 아닌 구역의 최상위 문단 목록(Block 처럼 .el 만 사용)."""
        cache = getattr(self, '_sec_cache', None)
        if cache is None:
            cache = self._sec_cache = {}
        if section not in cache:
            names = self.pkg.section_names()
            if section >= len(names):
                raise BuildError(f'clone: 구역 {section} 이(가) 없습니다(구역 수 {len(names)}).')
            cache[section] = list(self.pkg.section_root(section).findall(HP + 'p'))
        return cache[section]

    @staticmethod
    def _strip_section_defs(el):
        """복제한 문단 안의 구역 정의(secPr)와 단 나누기 정의를 제거(문서 안에 구역 정의가 둘 되지 않도록)."""
        for sp in list(el.iter(HP + 'secPr')):
            sp.getparent().remove(sp)
        for ctrl in list(el.iter(HP + 'ctrl')):
            if ctrl.find(HP + 'colPr') is not None:
                ctrl.getparent().remove(ctrl)

    def _replace_text(self, el, mapping):
        """복제한 요소 안의 모든 문단에서 문구 치환. 한 글자 덩어리 안이면 서식을 보존하고,
        여러 덩어리에 걸친 문구가 남아 있으면 문단 전체를 합쳐 치환한다."""
        for p in el.iter(HP + 'p'):
            if not own_ts(p):
                continue
            for old, new in mapping.items():
                for t in own_ts(p):
                    s = ''.join(t.itertext())
                    if old in s:
                        _set_t(t, s.replace(old, new))
                full = ''.join(''.join(t.itertext()) for t in own_ts(p))
                if old in full:
                    set_text(p, full.replace(old, new))

    def _fill_paras(self, spec, out, paras):
        """복제한 블록 안 '글이 있는 문단'(순서대로 0번부터)을 paras 로 바꾼다.
        - 문자열: 다음 문단 자리에 글을 넣는다(글자 모양은 바뀐 곳만 새로).
        - {"like": k, "text": "…"}: k번 문단의 모양을 그대로 복제한 **새 문단**을 바로 앞 문단 뒤에 끼워 넣는다(자리를 쓰지 않음).
        끼워 넣기를 쓰면 남는 원래 문단은 지운다(칸 안의 마지막 문단은 비움)."""
        slots = [p for el in out for p in el.iter(HP + 'p')
                 if not (p is el and el.find('.//' + HP + 'tbl') is not None) and ptext(p).strip()]
        n_slots = len(slots)
        plain = [x for x in paras if not isinstance(x, dict)]
        structured = len(plain) != len(paras) or bool(spec.get('trim'))
        if not structured and n_slots != len(plain):
            self.warnings.append(f'clone {spec.get("from")}번 블록에는 글이 있는 문단이 {n_slots}개인데 paras 는 {len(plain)}개입니다'
                                 '(모자란 문단은 비워지고 남는 글은 버려집니다).')
        if structured and len(plain) > n_slots:
            self.warnings.append(f'clone {spec.get("from")}번 블록: 글 자리가 {n_slots}개인데 문자열 paras 가 {len(plain)}개입니다'
                                 '(남는 글은 {"like":번호,"text":…} 로 끼워 넣으세요).')
        orig = [copy.deepcopy(p) for p in slots]
        at_box = [p.getparent() is slots[0].getparent() for p in slots]     # 큰 칸(첫 문단이 있는 칸)에 바로 놓인 문단인가
        box_level = slots[0].getparent() if slots else None
        used = 0
        last = None
        for item in paras:
            if isinstance(item, dict):
                k = int(item.get('like', 0))
                if not (0 <= k < n_slots):
                    self.warnings.append(f'clone {spec.get("from")}번 블록: like {k} 는 범위 밖입니다(0~{n_slots - 1}).')
                    continue
                new = copy.deepcopy(orig[k])
                set_text_keep(new, str(item.get('text', '')))
                if last is None:
                    slots[0].addprevious(new)
                else:
                    anchor = last
                    if at_box[k]:       # 안쪽 표의 칸 안에서 끝났더라도, 큰 칸 수준의 문단은 표 바깥(표를 품은 문단 뒤)에 놓는다
                        while anchor.getparent() is not None and anchor.getparent() is not box_level:
                            anchor = anchor.getparent()
                    anchor.addnext(new)
                last = new
            elif used < n_slots:
                set_text_keep(slots[used], item)
                last = slots[used]
                used += 1
        for p in slots[used:]:
            parent = p.getparent()
            if structured and parent is not None and sum(1 for c in parent if c.tag == HP + 'p') > 1:
                parent.remove(p)
            else:
                set_text_keep(p, '')

    def make_clone(self, spec):
        """서식의 블록(들)을 그대로 복제. texts(순서대로 교체) / text(문단 전체 교체) / replace(문구 치환) 지원.
        from..to 로 구간 복제, section 으로 다른 구역의 블록 복제."""
        sec = int(spec.get('section', 0))
        i = int(spec['from'])
        j = int(spec.get('to', i))
        if sec == 0:
            blocks = [b.el for b in self.bp.blocks]
        else:
            blocks = self._other_blocks(sec)
        if not (0 <= i <= j < len(blocks)):
            raise BuildError(f'clone: 블록 번호 범위가 잘못됨 {i}~{j} (총 {len(blocks)}개)')
        sec_block = next((b for b in self.bp.blocks if b.info.get('has_sec')), None)
        out = []
        for k in range(i, j + 1):
            el = copy.deepcopy(blocks[k])
            strip_ls(el)
            keep_sec = sec == 0 and sec_block is not None and k == sec_block.idx and spec.get('keep_section', True)
            if not keep_sec:
                self._strip_section_defs(el)
            out.append(el)
        texts = spec.get('texts')
        if texts is not None:
            idx = 0
            for el in out:
                for p in el.iter(HP + 'p'):
                    for t in own_ts(p):
                        if ''.join(t.itertext()).strip():
                            _set_t(t, texts[idx] if idx < len(texts) else '')
                            idx += 1
        if spec.get('text') is not None and len(out) == 1:
            el = out[0]
            if el.find('.//' + HP + 'tbl') is None:
                set_text_keep(el, spec['text'])
            else:
                targets = [p for p in el.iter(HP + 'p') if p is not el and ptext(p).strip()]
                if targets:
                    set_text_keep(targets[0], spec['text'])
        paras = spec.get('paras')
        if paras is not None:              # 글이 있는 문단을 차례로 바꿈(문단 안 글자 모양은 바뀐 곳만 새로)
            self._fill_paras(spec, out, paras)
        if spec.get('replace'):
            for el in out:
                self._replace_text(el, spec['replace'])
        if spec.get('scale_height'):             # 한 쪽을 꽉 채운 양식이 다른 쪽 여백 설정에서 넘칠 때: 바깥 표의 최소 높이를 비율로 줄인다
            f = float(spec['scale_height'])
            for el in out:
                for tbl in el.iter(HP + 'tbl'):
                    if any(a.tag == HP + 'tbl' for a in tbl.iterancestors()):
                        continue
                    sz = tbl.find(HP + 'sz')
                    if sz is not None and sz.get('height'):
                        sz.set('height', str(int(int(sz.get('height')) * f)))
                    for tr in tbl.findall(HP + 'tr'):
                        for tc in tr.findall(HP + 'tc'):
                            cs = tc.find(HP + 'cellSz')
                            if cs is not None and cs.get('height'):
                                cs.set('height', str(int(int(cs.get('height')) * f)))
        for el in out:
            self._renew_tables(el)
        return out

    # ---- 전체 조립 ------------------------------------------------------
    def _spec_key(self, s):
        """블록 사이 간격을 정할 때 쓰는 역할 이름(서식 관찰과 같은 이름)."""
        typ = s.get('type', 'paragraph')
        if typ == 'bullet':
            n = max(1, len(self.kit.bullet_levels))
            return f'bullet{min(int(s.get("level", 1)), n)}'
        if typ in ('end', 'paragraph'):
            return 'paragraph'
        if typ in ('gallery',):
            return 'table'
        if typ in ('title',):
            return 'cover'
        if typ in ('clone', 'like', 'blank', 'image'):
            return None
        return typ

    def build(self, specs, compact=0):
        """specs: 블록 dict 목록 → (top-level 문단 목록, 프로브 목록)."""
        self._compact = compact
        kit = self.kit
        out = []          # (el, auto_blank?)
        probes = []
        sec_block = next((b for b in self.bp.blocks if b.info.get('has_sec')), None)
        title_spec = next((s for s in specs if s.get('type') == 'title'), None)
        sub_spec = next((s for s in specs if s.get('type') == 'subtitle'), None)
        cover_els = None
        if title_spec is not None and self.bp.cover_end > 0:
            cover_els = self.make_cover(title_spec.get('text', ''), (sub_spec or {}).get('text'),
                                        title_spec.get('fields'))
        cover_has_sec = bool(cover_els) and sec_block is not None and sec_block.idx < self.bp.cover_end
        sec_cloned = any(s.get('type') in ('clone', 'like') and int(s.get('section', 0)) == 0
                         and int(s['from']) <= sec_block.idx <= int(s.get('to', s['from']))
                         for s in specs) if sec_block is not None else False
        if sec_block is not None and not cover_has_sec and not sec_cloned:
            el = self._clone(sec_block)
            for t in list(el.iter(HP + 'tbl')):
                t.getparent().remove(t)
            for p in el.iter(HP + 'p'):
                for tt in own_ts(p):
                    _set_t(tt, '')
            out.append((el, False))
        n = len(specs)
        prev_key = None
        for si, s in enumerate(specs):
            extra_els = []
            typ = s.get('type', 'paragraph')
            role = typ
            el = None
            text = s.get('text', '')
            cls = s.get('class') or s.get('cls')
            if typ == 'subtitle' and cover_els is not None:
                continue                       # 부제는 표지 안에 이미 들어감
            if typ == 'title' and cover_els is not None:
                el, extra_els = cover_els[0], cover_els[1:]
                role = 'cover'
            elif typ == 'title':
                el = self.make_title(text, s.get('fields'))
                if el is None:
                    el = self._first(('heading_text', text), ('paragraph', text))
            elif typ == 'subtitle':
                el = self._first(('subtitle', text), ('paragraph', text))
            elif typ == 'heading':
                el = self.make_simple('heading', text, cls=cls)
                pr = kit.proto('heading', text=text, cls=cls)
                role = 'heading'
                if el is None:
                    el = self.make_simple('paragraph', text)
                    role = 'paragraph'
            elif typ in ('bullet', 'numbered', 'paragraph', 'end'):
                if typ == 'end':
                    text = text or '끝.'
                lvl = int(s.get('level', 1))
                if typ == 'bullet':
                    el = self.make_simple('bullet', text, lvl, cls)
                    if el is not None and not cls and lvl > len(kit.bullet_levels) and lvl > 1:
                        extra = lvl - len(kit.bullet_levels)
                        set_bullet_text(el, text, marker=' - ')
                        el.set('paraPrIDRef', self.indented_para(el.get('paraPrIDRef'), 1300 * extra))
                    if el is None:
                        el = self._first(('numbered', '· ' + text), ('paragraph', '· ' + text))
                        role = 'paragraph'
                elif typ == 'numbered':
                    el = self._first(('numbered', text), ('paragraph', text))
                    if cls:
                        el2 = self.make_simple('numbered', text, cls=cls)
                        el = el2 if el2 is not None else el
                else:
                    el = self.make_simple('paragraph', text, cls=cls)
                    if el is None:
                        el = self._first(('numbered', text))
                if el is None:
                    b = kit.proto('bullet')
                    if b is not None:
                        el = self.make_simple('bullet', text)
                        for t in own_ts(el):
                            if is_bullet_start(''.join(t.itertext())):
                                _set_t(t, ''.join(t.itertext()).replace(bullet_marker(''.join(t.itertext())), '', 1))
                                break
            elif typ == 'box':
                lines = s.get('lines') or ([text] if text else [])
                el = self.make_box(lines, s.get('title'), cls)
                if el is None:
                    self.warnings.append('서식에 강조 박스가 없어 글머리 문단으로 대체했습니다.')
                    for ln in ([s.get('title')] if s.get('title') else []) + lines:
                        e2 = self._first(('bullet', ln), ('paragraph', ln))
                        out.append((e2, False))
                    continue
            elif typ == 'table':
                el = self.make_table(s)
                if el is None:
                    self.warnings.append('서식에 표가 없어 표를 글머리 문단으로 대체했습니다.')
                    hdr = s.get('header') or []
                    hdr = hdr[0] if hdr and isinstance(hdr[0], list) else hdr
                    for r in s.get('rows', []):
                        cells = [self._norm_cell(c)['lines'][0] for c in r]
                        line = ', '.join(f'{h}: {c}' for h, c in zip(hdr, cells)) if hdr else ' / '.join(cells)
                        e2 = self._first(('bullet', line), ('paragraph', line))
                        out.append((e2, False))
                    continue
            elif typ == 'image':
                els = self.make_image_block(s)
                el, extra_els = els[0], els[1:]
                role = 'paragraph'
            elif typ == 'gallery':
                el = self.make_gallery(s)
                role = 'table'
                if el is None:
                    continue
            elif typ == 'blank':
                out.append((kit.blank_el(), False))
                prev_key = None
                continue
            elif typ in ('clone', 'like'):
                els = self.make_clone(s)
                el, extra_els = els[0], els[1:]
                role = 'clone'
            else:
                raise BuildError(f'알 수 없는 블록 type: {typ}')
            if el is None:
                raise BuildError(f'서식에서 "{typ}" 에 쓸 수 있는 요소를 찾지 못했습니다.')
            key = self._spec_key(s) if typ != 'title' or cover_els is not None else 'heading'
            if typ == 'heading':
                key = 'heading'
            # 앞 블록과의 간격: 서식에서 같은 '앞 역할 → 뒤 역할' 사이에 둔 빈 줄을 따른다
            if prev_key is not None and key is not None and not s.get('no_gap') and not s.get('page_break'):
                blanks = kit.gap(prev_key, key)
                if compact >= 1:
                    blanks = blanks[:1]
                if compact >= 2 and key != 'heading':
                    blanks = []
                for b in blanks:
                    out.append((kit.blank_el(b), True))
            if typ not in ('clone', 'like', 'title') or s.get('text'):
                self._apply_inline(el)
            if s.get('page_break'):
                el.set('pageBreak', '1')
            if el.get('pageBreak') == '1' and out:
                while out and (out[-1][1] or self._is_blank_p(out[-1][0])):
                    out.pop()
            out.append((el, False))
            for x in extra_els:
                out.append((x, False))
            probes.append(self._probe(si, typ, s))
            prev_key = key if key is not None else None
            if typ in ('clone', 'like'):
                prev_key = None
        while out and out[-1][1]:
            out.pop()
        if kit.unknown_classes:
            self.warnings.append('알 수 없는 서식 종류 표시를 무시했습니다: ' + ', '.join(sorted(kit.unknown_classes))
                                 + ' (hwpx_analyze 의 "서식 종류" 목록에 있는 이름만 쓸 수 있습니다)')
        return [e for e, _ in out], probes

    @staticmethod
    def _is_blank_p(el):
        if el.tag != HP + 'p' or el.get('pageBreak') == '1':
            return False
        if el.find('.//' + HP + 'tbl') is not None or el.find('.//' + HP + 'pic') is not None:
            return False
        if el.find('.//' + HP + 'secPr') is not None:
            return False
        for run in el.findall(HP + 'run'):
            for ch in run:
                if ch.tag not in (HP + 't', HP + 'ctrl'):
                    return False
        return not ptext(el).strip()

    @staticmethod
    def _probe(si, typ, s):
        def first(x):
            if isinstance(x, dict):
                x = x.get('text', '')
            if isinstance(x, list):
                x = x[0] if x else ''
            return str(x).split('\n')[0].strip()

        pr = {'i': si, 'type': typ, 'texts': []}
        if typ in ('clone', 'like'):
            raw = s.get('probe') or s.get('text') or ''.join(str(x) for x in (s.get('texts') or []))
            t = re.sub(r'\s+', ' ', str(raw)).strip()
            pr['texts'] = [t[:12]] if t else []
            if s.get('qa') == 'heading':
                pr['type'] = 'heading'
        elif typ in ('heading', 'title', 'subtitle', 'paragraph', 'bullet', 'numbered', 'end'):
            t = re.sub(r'\s+', ' ', s.get('text', ''))
            pr['texts'] = [t[:12]]
        elif typ == 'image':
            pr['texts'] = [str(s.get('caption', ''))[:12]]
        elif typ == 'gallery':
            caps = [x.get('caption', '') for x in s.get('images', []) if isinstance(x, dict)]
            pr['texts'] = [caps[0][:12]] if caps else []
        elif typ == 'box':
            lines = s.get('lines') or []
            pr['texts'] = [first(s.get('title') or (lines[0] if lines else ''))[:12]]
        elif typ == 'table':
            rows = s.get('rows') or []
            hdr = s.get('header') or []
            hdr = hdr[0] if hdr and isinstance(hdr[0], list) else hdr
            texts = []
            for r in rows[:16]:
                cands = []
                for cell in r:
                    t = re.sub(r'^[\s❍○●■□▪·※\-\*]+', '', first(cell))[:12]
                    cands.append(t)
                pick = next((t for t in cands if len(t) >= 3), None) or max(cands, key=len, default='')
                texts.append(pick)
            if not texts and hdr:
                texts = [first(hdr[0])[:10]]
            pr['texts'] = texts
        pr['texts'] = [t for t in pr['texts'] if len(t) >= 2]
        return pr

    # ---- 저장 ---------------------------------------------------------
    def write(self, elements, out_path, title=None, preview_text=None):
        pkg = self.pkg
        root = self.bp.root
        for ch in list(root):
            root.remove(ch)
        for e in elements:
            root.append(e)
        pkg.set_xml(pkg.section_names()[0], root)
        register_images(pkg, self._img_new)
        if 'settings.xml' in pkg.files:   # 문서에 저장된 '모아찍기' 같은 인쇄 설정이 PDF 에 영향을 주지 않도록 초기화
            st = pkg.files['settings.xml'].decode('utf-8', 'ignore')
            st = re.sub(r'(name="PrintMethod" type="short">)\d+(<)', r'\g<1>0\g<2>', st)
            pkg.files['settings.xml'] = st.encode('utf-8')
        self.head.root.set('secCnt', '1')   # 첫 구역만 남기므로 구역 수 일치시킴(안 맞으면 한글이 열지 못함)
        pkg.set_xml('Contents/header.xml', self.head.root)
        # 첫 구역 외 구역 제거
        extra = pkg.section_names()[1:]
        if extra and 'Contents/content.hpf' in pkg.files:
            hpf = etree.fromstring(pkg.files['Contents/content.hpf'])
            for name in extra:
                href = name
                for it in list(hpf.iter('{%s}item' % NS['opf'])):
                    if it.get('href') == href:
                        iid = it.get('id')
                        it.getparent().remove(it)
                        for ir in list(hpf.iter('{%s}itemref' % NS['opf'])):
                            if ir.get('idref') == iid:
                                ir.getparent().remove(ir)
                pkg.files.pop(name, None)
            pkg.files['Contents/content.hpf'] = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8',
                                                                 standalone=True)
        if title and 'Contents/content.hpf' in pkg.files:
            hpf = etree.fromstring(pkg.files['Contents/content.hpf'])
            for t in hpf.iter('{%s}title' % NS['opf']):
                t.text = title
            pkg.files['Contents/content.hpf'] = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8',
                                                                 standalone=True)
        if 'Preview/PrvText.txt' in pkg.files:
            pkg.files['Preview/PrvText.txt'] = (preview_text or (title or '')).encode('utf-8')
        pkg.save(out_path)
        return out_path
