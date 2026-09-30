# -*- coding: utf-8 -*-
"""서식 복제 빌더: 분석된 서식의 요소를 그대로 복제해 새 내용으로 채운 HWPX 를 만든다."""
from __future__ import annotations

import copy
import math
import os
import re
import statistics

from lxml import etree

from .analyze import (Block, Blueprint, analyze, bullet_marker, cell_paragraphs, is_bullet_start, ptext,
                      table_of)
from .images import (ImageError, MM, fit_size, next_image_index, pic_run, prepare_image, register_images)
from .package import HH, HP, NS

HEADING_SPLIT = re.compile(r'^(\S{1,6}\s*[\.\)]\s*)(.*)$', re.S)


class BuildError(Exception):
    pass


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
    _set_t(ts[0], text)
    for t in ts[1:]:
        _set_t(t, '')


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
        if is_bullet_start(''.join(t.itertext())):
            k = i
            break
    if k is None:
        set_text(p, (marker or '') + text)
        return
    cur = ''.join(ts[k].itertext())
    mk = bullet_marker(cur) if marker is None else marker
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


# ---------------------------------------------------------------- 서식 키트
class Kit:
    def __init__(self, bp: Blueprint):
        self.bp = bp
        self.head = bp.head
        self.by_role = {}
        for b in bp.blocks:
            self.by_role.setdefault(b.role, []).append(b)
        self._learn_bullets()
        self._learn_spacing()
        self._learn_tables()
        self.text_width = min(bp.page['text_width'] - 400, 47900) if bp.page['text_width'] > 0 else 47000
        if self.table_default is not None:
            self.text_width = int(self.table_default.info['tbl'].find(HP + 'sz').get('width'))

    # ---- 글머리 단계
    def _learn_bullets(self):
        groups = {}
        for b in self.by_role.get('bullet', []):
            key = (b.info.get('marker', '').strip(), b.info.get('left', 0))
            groups.setdefault(key, []).append(b)
        levels = []
        for key, lst in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[1][0].idx)):
            # 같은 단계 안에서 가장 흔한 문단 서식의 첫 블록을 대표로
            cnt = {}
            for b in lst:
                cnt.setdefault(b.info['para_pr'], []).append(b)
            levels.append(max(cnt.values(), key=len)[0])
        self.bullet_levels = levels

    NUM_CLASSES = [r'^\s*\d{1,2}\s*\.', r'^\s*[가-힣]\s*\.', r'^\s*\d{1,2}\s*\)', r'^\s*[가-힣]\s*\)',
                   r'^\s*\(\d{1,2}\)', r'^\s*[①-⑳]']

    def num_class(self, text):
        for i, pat in enumerate(self.NUM_CLASSES):
            if re.match(pat, text or ''):
                return i
        return None

    def numbered_proto(self, text):
        lst = self.by_role.get('numbered', [])
        if not lst:
            return None
        cls = {}
        for b in lst:
            c = self.num_class(b.text)
            if c is not None:
                cls.setdefault(c, b)
        want = self.num_class(text)
        if want in cls:
            return cls[want]
        if not cls:
            return lst[0]
        ordered = sorted(cls.items(), key=lambda kv: (self.head.para.get(kv[1].info['para_pr'], {}).get('left', 0), kv[0]))
        depth = min(want if want is not None else 0, len(ordered) - 1)
        return ordered[depth][1]

    def numbered_extra(self, text):
        """서식에 없는 더 깊은 번호 단계(예: 1) 가) )는 마지막 단계에서 몇 단계 더 들여쓸지."""
        lst = self.by_role.get('numbered', [])
        cls = {self.num_class(b.text) for b in lst if self.num_class(b.text) is not None}
        want = self.num_class(text)
        if want is None or want in cls or not cls:
            return 0
        return max(0, min(want, 5) - (len(cls) - 1))

    def proto(self, role, level=1, text=None):
        if role == 'numbered':
            return self.numbered_proto(text)
        if role == 'bullet':
            if not self.bullet_levels:
                return None
            return self.bullet_levels[min(level, len(self.bullet_levels)) - 1]
        if role == 'table' and getattr(self, 'table_default', None) is not None:
            return self.table_default
        lst = self.by_role.get(role)
        return lst[0] if lst else None

    # ---- 빈 줄(간격) 학습
    def _learn_spacing(self):
        obs = {}
        blocks = self.bp.blocks
        for i, b in enumerate(blocks):
            if b.role == 'blank':
                continue
            j = i + 1
            blanks = []
            while j < len(blocks) and blocks[j].role == 'blank' and len(blanks) < 2:
                blanks.append(blocks[j])
                j += 1
            nxt = blocks[j].role if j < len(blocks) else None
            if blanks:
                obs.setdefault(b.role, []).append(tuple(blanks))
        self.after = {}
        for role, lst in obs.items():
            sigs = {}
            for tup in lst:
                sig = tuple((x.info['para_pr'], x.info['style']) for x in tup)
                sigs.setdefault(sig, []).append(tup)
            best = max(sigs.values(), key=len)
            self.after[role] = list(best[0])
        blanks = self.by_role.get('blank', [])
        self.default_blank = blanks[0] if blanks else None

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
    def _learn_one(self, tb):
        cells, cols, rows = tb.info['cells'], tb.info['cols'], tb.info['rows']
        hdr_rows = 0
        for r in range(rows):
            rc = [c for c in cells if c['r'] == r]
            if rc and all(c['filled'] for c in rc):
                hdr_rows += 1
            else:
                break
        hdr_rows = hdr_rows or 1
        tb.info['hdr_rows'] = hdr_rows
        cls, body, heads, bodies = {}, {}, [], []
        for c in cells:
            rk = 'head' if c['r'] < hdr_rows else ('lastbody' if c['r'] + c['rs'] >= rows else 'body')
            if c['cs'] >= cols:
                ck = 'full'
            elif c['c'] == 0:
                ck = 'first'
            elif c['c'] + c['cs'] >= cols:
                ck = 'last'
            else:
                ck = 'mid'
            if (c['rs'] > 1 or c['cs'] > 1) and rk != 'head':
                continue
            cls.setdefault((rk, ck), c)
            if rk != 'head':
                al = self.head.para.get(c['para_pr'], {}).get('align', 'JUSTIFY')
                body.setdefault('c' if al == 'CENTER' else 'l', (c['para_pr'], c['char'], c['style']))
                bodies.append(c['h'])
            else:
                heads.append(c['h'])
        return {'cls': cls, 'body': body, 'head_h': min(heads) if heads else None,
                'body_h': min(bodies) if bodies else None, 'width': int(tb.info['tbl'].find(HP + 'sz').get('width'))}

    @staticmethod
    def _pick(cls, rk, ck):
        order_col = {'first': ['first', 'mid', 'last', 'full'], 'mid': ['mid', 'last', 'first', 'full'],
                     'last': ['last', 'mid', 'first', 'full'], 'full': ['full', 'first', 'mid', 'last']}[ck]
        order_row = {'head': ['head'], 'body': ['body', 'lastbody'], 'lastbody': ['lastbody', 'body']}[rk]
        for r in order_row:
            for c in order_col:
                if (r, c) in cls:
                    return cls[(r, c)]
        for c in order_col:
            for r in ('head', 'body', 'lastbody'):
                if (r, c) in cls:
                    return cls[(r, c)]
        return None

    def _learn_tables(self):
        self.tables = self.by_role.get('table', [])
        self.cls = {}          # 전역(장식 표 제외) 셀 서식
        self.body = {}
        self.table_kits = {}
        heads, bodies = [], []
        self.table_default = None
        for tb in self.tables:
            one = self._learn_one(tb)
            self.table_kits[tb.idx] = one
            has_pic = any(True for _ in tb.el.iter(HP + 'pic'))
            eligible = tb.info['cols'] <= 12 and tb.info.get('fills', 0) > 0 and not has_pic
            if not eligible:
                continue
            if self.table_default is None:
                self.table_default = tb
            for k, v in one['cls'].items():
                self.cls.setdefault(k, v)
            for k, v in one['body'].items():
                self.body.setdefault(k, v)
            if one['head_h']:
                heads.append(one['head_h'])
            if one['body_h']:
                bodies.append(one['body_h'])
        if self.table_default is None and self.tables:
            self.table_default = self.tables[0]
            for k, v in self.table_kits[self.tables[0].idx]['cls'].items():
                self.cls.setdefault(k, v)
            for k, v in self.table_kits[self.tables[0].idx]['body'].items():
                self.body.setdefault(k, v)
        self.head_h = min(heads) if heads else 2148
        self.body_h = min(bodies) if bodies else 2000

    def cell_rec(self, rk, ck):
        return self._pick(self.cls, rk, ck)

    def table_kit(self, idx=None):
        return TableKit(self, self.table_kits.get(int(idx)) if idx is not None else None)


class TableKit:
    """표 하나를 만들 때 쓰는 서식 묶음: 지정한 표(proto)의 서식을 우선, 없으면 전역 서식."""

    def __init__(self, kit, own):
        self.kit, self.own = kit, own
        self.body = dict(kit.body)
        if own:
            self.body.update(own['body'])
        self.head_h = (own or {}).get('head_h') or kit.head_h
        self.body_h = (own or {}).get('body_h') or kit.body_h

    def cell_rec(self, rk, ck):
        if self.own:
            r = self.kit._pick(self.own['cls'], rk, ck)
            if r is not None:
                return r
        return self.kit.cell_rec(rk, ck)


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

    # ---- 개별 블록 생성 -------------------------------------------------
    def _clone(self, blk):
        el = copy.deepcopy(blk.el)
        strip_ls(el)
        return el

    def make_title(self, text, fields=None):
        pr = self.kit.proto('title')
        if pr is None:
            return None
        el = self._clone(pr)
        nodes = []   # (문단, 글자크기) — 글이 있는 문단을 문서 순서대로
        for p in el.iter(HP + 'p'):
            t = ptext(p)
            if not t.strip():
                continue
            r = p.find(HP + 'run')
            size = self.head.size(r.get('charPrIDRef')) if r is not None else 0
            nodes.append((p, size, t))
        if fields:
            for i, (p, _sz, _t) in enumerate(nodes):
                set_text(p, fields[i] if i < len(fields) else '')
            if len(fields) > len(nodes):
                self.warnings.append(f'제목 블록에는 글 칸이 {len(nodes)}개뿐이라 fields 의 나머지는 무시했습니다.')
        elif nodes:
            best = max(nodes, key=lambda n: (n[1], len(n[2])))
            set_text(best[0], text)
            others = [n[2] for n in nodes if n[0] is not best[0]]
            if others:
                self.warnings.append('제목 블록에 서식 원문의 다른 글이 그대로 남았습니다: ' + ', '.join(o[:12] for o in others[:6])
                                     + ' → 바꾸려면 title 블록에 "fields":[…](글 칸 순서대로)를 쓰세요.')
        self._renew_tables(el)
        return el

    def make_simple(self, role, text, level=1):
        pr = self.kit.proto(role, level, text)
        if pr is None:
            return None
        el = self._clone(pr)
        if pr.info.get('tbl') is not None:      # 표형(소제목 등)
            target = None
            for p in el.iter(HP + 'p'):
                if p is el:
                    continue
                if ptext(p).strip():
                    target = p
                    break
            if target is None:
                for p in el.iter(HP + 'p'):
                    if p is not el:
                        target = p
                        break
            (set_heading_text if role == 'heading' else set_text)(target, text)
            self._renew_tables(el)
        else:
            if role == 'numbered':
                ex = self.kit.numbered_extra(text)
                if ex:
                    el.set('paraPrIDRef', self.indented_para(el.get('paraPrIDRef'), 1300 * ex))
            if role == 'bullet':
                set_bullet_text(el, text)
            elif role == 'heading_text':
                set_heading_text(el, text)
            else:
                set_text(el, text)
        return el

    def _first(self, *cands):
        for role, text in cands:
            el = self.make_simple(role, text)
            if el is not None:
                return el
        return None

    def make_box(self, lines, title=None):
        pr = self.kit.proto('box')
        if pr is None:
            return None
        el = self._clone(pr)
        sub = el.find('.//' + HP + 'subList')
        ps = sub.findall(HP + 'p')
        head_p = ps[0]
        body_p = ps[1] if len(ps) > 1 else ps[0]
        for q in ps:
            sub.remove(q)
        seq = ([(title, head_p)] if title else []) + [(ln, body_p) for ln in lines]
        for text, proto in seq:
            q = copy.deepcopy(proto)
            strip_ls(q)
            set_text(q, text)
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
            data, ext, wpx, hpx = prepare_image(full)
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
        if 'c' in kit.body:
            return kit.body['c']
        if 'l' in kit.body:
            pp, ch, st = kit.body['l']
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
        if spec.get('proto') is not None:
            pr = self.bp.blocks[int(spec['proto'])]
            if pr.role != 'table':
                raise BuildError(f'table.proto: {spec["proto"]}번 블록은 표가 아닙니다.')
            kit = kit0.table_kit(pr.idx)
            text_w = kit0.table_kits[pr.idx]['width']
        else:
            pr = kit0.proto('table')
            kit = kit0.table_kit(None)
            text_w = kit0.text_width
        if pr is None:
            return None
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
        widths = spec.get('widths') or [1] * ncols
        if len(widths) != ncols:
            widths = [1] * ncols
            self.warnings.append(f'표의 widths 개수가 열 수({ncols})와 달라 균등 분할했습니다.')
        total = spec.get('width') or text_w
        ws = [int(total * w / sum(widths)) for w in widths]
        ws[-1] += total - sum(ws)
        ws = self._fit_widths(ws, placed, len(hnorm))
        aligns = spec.get('align') or spec.get('aligns') or []
        aligns = [(a or 'c')[0].lower() for a in aligns]
        aligns += ['c'] * (ncols - len(aligns))
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
            rk = 'head' if is_head else ('lastbody' if r + cell['rs'] >= nrows else 'body')
            if cell['cs'] >= ncols:
                ck = 'full'
            elif c == 0:
                ck = 'first'
            elif c + cell['cs'] >= ncols:
                ck = 'last'
            else:
                ck = 'mid'
            rec = kit.cell_rec(rk, ck)
            if rec is None:
                return None
            w = sum(ws[c:c + cell['cs']])
            # 문단/글자 서식 선택
            if is_head:
                pp, ch, st = rec['para_pr'], rec['char'], rec['style']
                al = 'c'
            else:
                al = (cell['align'] or aligns[c])[0].lower()
                rec_al = self.head.para.get(rec['para_pr'], {}).get('align', 'JUSTIFY')
                if al == 'c':
                    pp, ch, st = (rec['para_pr'], rec['char'], rec['style']) if rec_al == 'CENTER' else \
                        kit.body.get('c') or (self.ensure_para(rec['para_pr'], 'CENTER'), rec['char'], rec['style'])
                elif al == 'r':
                    pp = self.ensure_para(rec['para_pr'], 'RIGHT')
                    ch, st = rec['char'], rec['style']
                else:
                    pp, ch, st = (rec['para_pr'], rec['char'], rec['style']) if rec_al in ('JUSTIFY', 'LEFT') else \
                        kit.body.get('l') or (self.ensure_para(rec['para_pr'], 'LEFT'), rec['char'], rec['style'])
            tc = copy.deepcopy(rec['el'])
            tc.set('borderFillIDRef', rec['bf'])
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
            for line in text_lines:
                sub.append(new_p(ref_p, line, para_pr=pp, char=ch, style=st))
            tc.find(HP + 'cellAddr').set('colAddr', str(c))
            tc.find(HP + 'cellAddr').set('rowAddr', str(r))
            tc.find(HP + 'cellSpan').set('colSpan', str(cell['cs']))
            tc.find(HP + 'cellSpan').set('rowSpan', str(cell['rs']))
            size = self.head.size(ch or '0', 1000)
            mar = tc.find(HP + 'cellMargin')
            inner = w - (int(mar.get('left', '141')) + int(mar.get('right', '141'))) - 200
            cpl = max(2, inner / (size * 0.94))
            nlines = sum(max(1, math.ceil(dwidth(l) / cpl)) for l in text_lines)
            base = kit.head_h if is_head else kit.body_h
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
            floating = sum(row_h) > 0.4 * usable      # 한 쪽에 가까운 큰 표: 글자처럼 취급하면 쪽 끝에서 잘릴 수 있음
        if floating:
            tbl.find(HP + 'pos').set('treatAsChar', '0')
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
                set_text(el, spec['text'])
            else:
                targets = [p for p in el.iter(HP + 'p') if p is not el and ptext(p).strip()]
                if targets:
                    set_text(targets[0], spec['text'])
        if spec.get('replace'):
            for el in out:
                self._replace_text(el, spec['replace'])
        for el in out:
            self._renew_tables(el)
        return out

    # ---- 전체 조립 ------------------------------------------------------
    def build(self, specs, compact=0):
        """specs: 블록 dict 목록 → (top-level 문단 목록, 프로브 목록)."""
        self._compact = compact
        kit = self.kit
        out = []          # (el, auto_blank?)
        probes = []
        sec_block = next((b for b in self.bp.blocks if b.info.get('has_sec')), None)
        title_spec = next((s for s in specs if s.get('type') == 'title'), None)
        title_proto = kit.proto('title')
        first_is_title = bool(title_spec and title_proto is not None and sec_block is not None
                              and title_proto.idx == sec_block.idx)
        sec_cloned = any(s.get('type') in ('clone', 'like') and int(s.get('section', 0)) == 0
                         and int(s['from']) <= sec_block.idx <= int(s.get('to', s['from']))
                         for s in specs) if sec_block is not None else False
        if sec_block is not None and not first_is_title and not sec_cloned:
            el = self._clone(sec_block)
            for t in list(el.iter(HP + 'tbl')):
                t.getparent().remove(t)
            for p in el.iter(HP + 'p'):
                for tt in own_ts(p):
                    _set_t(tt, '')
            out.append((el, False))
        prev_role = None
        n = len(specs)
        for si, s in enumerate(specs):
            extra_els = []
            typ = s.get('type', 'paragraph')
            nxt = specs[si + 1].get('type') if si + 1 < n else None
            role = typ
            el = None
            text = s.get('text', '')
            if typ == 'title':
                el = self.make_title(text, s.get('fields'))
                if el is None:
                    el = self._first(('heading_text', text), ('paragraph', text))
            elif typ == 'subtitle':
                el = self._first(('subtitle', text), ('paragraph', text))
            elif typ == 'heading':
                el = self._first(('heading', text), ('heading_text', text))
                role = 'heading' if kit.proto('heading') else 'heading_text'
                if el is None:
                    el = self.make_simple('paragraph', text)
                    role = 'paragraph'
            elif typ in ('bullet', 'numbered', 'paragraph', 'end'):
                if typ == 'end':
                    text = text or '끝.'
                lvl = int(s.get('level', 1))
                if typ == 'bullet':
                    el = self.make_simple('bullet', text, lvl)
                    if el is not None and lvl > len(kit.bullet_levels) and lvl > 1:
                        extra = lvl - len(kit.bullet_levels)
                        set_bullet_text(el, text, marker=' - ')
                        el.set('paraPrIDRef', self.indented_para(el.get('paraPrIDRef'), 1300 * extra))
                    if el is None:
                        el = self._first(('numbered', '· ' + text), ('paragraph', '· ' + text))
                        role = 'paragraph'
                elif typ == 'numbered':
                    el = self._first(('numbered', text), ('paragraph', text))
                else:
                    el = self._first(('paragraph', text), ('numbered', text))
                if el is None:
                    b = kit.proto('bullet')
                    if b is not None:
                        el = self.make_simple('bullet', text)
                        for t in own_ts(el):
                            if is_bullet_start(''.join(t.itertext())):
                                _set_t(t, ''.join(t.itertext()).replace(bullet_marker(''.join(t.itertext())), '', 1))
                                break
                role = 'paragraph' if typ == 'end' else role
            elif typ == 'box':
                lines = s.get('lines') or ([text] if text else [])
                el = self.make_box(lines, s.get('title'))
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
                continue
            elif typ in ('clone', 'like'):
                els = self.make_clone(s)
                el, extra_els = els[0], els[1:]
                role = 'clone'
            else:
                raise BuildError(f'알 수 없는 블록 type: {typ}')
            if el is None:
                raise BuildError(f'서식에서 "{typ}" 에 쓸 수 있는 요소를 찾지 못했습니다.')
            if role in ('heading', 'heading_text') and len(out) > 3 and not s.get('page_break'):
                gap = 2 if compact == 0 else 1
                trail = 0
                for _e, _a in reversed(out):
                    if _a:
                        trail += 1
                    else:
                        break
                proto_blank = next((e for e, a in reversed(out) if a), None)
                if proto_blank is None:
                    bl = kit.after.get('table') or kit.after.get('paragraph') or kit.after.get('bullet') or []
                    proto_blank = kit.blank_el(bl[0]) if bl else None
                while proto_blank is not None and trail < gap:
                    out.append((copy.deepcopy(proto_blank), True))
                    trail += 1
            if s.get('page_break'):
                el.set('pageBreak', '1')
            if el.get('pageBreak') == '1' and out:
                while out and (out[-1][1] or self._is_blank_p(out[-1][0])):
                    out.pop()
            out.append((el, False))
            for x in extra_els:
                out.append((x, False))
            probes.append(self._probe(si, typ, s))
            # 자동 간격
            group_end = not (typ in ('bullet', 'numbered', 'paragraph') and nxt == typ)
            if group_end and nxt is not None and typ not in ('clone', 'like') and not s.get('no_gap'):
                blanks = kit.after.get(role if role != 'clone' else 'paragraph', [])
                if not blanks and typ == 'image':
                    blanks = kit.after.get('table') or kit.after.get('bullet') or []
                if typ in ('bullet', 'numbered', 'paragraph') and compact >= 1 and nxt != 'heading':
                    blanks = blanks[:0]
                if compact >= 1:
                    blanks = blanks[:1]
                if compact >= 2 and typ in ('table',):
                    blanks = []
                if nxt == 'blank':
                    blanks = []
                for b in blanks:
                    out.append((kit.blank_el(b), True))
            prev_role = typ
        while out and out[-1][1]:
            out.pop()
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
