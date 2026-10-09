# -*- coding: utf-8 -*-
"""보고서용 도표 — 데이터 몇 줄만 주면 같은 디자인의 PNG 를 그린다(AI 가 그림 코드를 짜지 않게).

종류(type)
  bar       세로 막대(월별 건수 등)            rows: 이름 | 값
  hbar      가로 막대(문항별 비율 등)          rows: 이름 | 값
  group     묶음 막대(사전·사후 평균 등)       rows: 이름 | 값1 | 값2 …   (값에 '3.18[2.9,3.4]' 처럼 신뢰구간)
  dumbbell  사전→사후 점 잇기                rows: 이름 | 사전 | 사후 [| 오른쪽 표시(예: d 1.05)]
  stack     100% 누적 가로 막대(응답 분포)    rows: 이름 | 비율1 | 비율2 …
  effect    효과 크기 막대(0.2·0.5·0.8 기준선)  rows: 이름 | 값 [| 작은 글(n=62) [| 묶음 이름]]
  hist      도수분포(변화량 분포 등)            rows: 구간 | 도수
  scatter   산점도 + 회귀선(r 자동)            rows: x | y
  line      꺾은선(여러 계열)                  rows: x | 값1 | 값2 …
  timeline  연혁·정책 흐름                    rows: 시기 | 설명(줄바꿈 '/') [| done]
  steps     절차(상자 + 화살표)                rows: 단계 | 시기 | 설명(줄바꿈 '/')
  cycle     순환 모형(가운데 제목 + 상자 2~6개)  rows: 제목 | 설명(줄바꿈 '/')

공통 옵션: label(도표 안 왼쪽 위 작은 제목), legend(쉼표), min, max, unit, note(아래 작은 글), accent(#RRGGBB),
           highlight(강조할 이름·번호, 쉼표), sort(desc|asc), decimals, width(기본 1340)

규칙: 축은 자르지 않는다(비율 0~100, 척도는 척도의 최솟값부터). 값은 막대 끝에 바로 쓴다. 색은 회색(비교 대상) + 강조 한 색.
논리 폭 1340 = 문서에 넣을 때 156mm, 글자 22단위 ≈ 7.3pt(인쇄해도 읽히는 최소 크기). 실제 픽셀은 2배로 그린다.
"""
from __future__ import annotations

import colorsys
import glob
import json
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

WHITE = (255, 255, 255)
INK = (30, 30, 34)
BODY = (70, 72, 78)
MUTED = (112, 116, 124)
FAINT = (168, 172, 178)
GRID = (230, 232, 236)
PRE = (174, 180, 187)
PRE_L = (220, 223, 227)
PAPER = (244, 245, 247)
DEFAULT_W = 1340          # 156mm 폭에 넣었을 때 글자 19~25단위가 6.3~8.3pt 가 되게(1600 이면 5.3~7pt 로 작음)


# ------------------------------------------------------------------ 색
def hex_rgb(h):
    h = h.strip().lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c, t, w):
    return tuple(int(round(a + (b - a) * w)) for a, b in zip(c, t))


def palette(accent='#8C1C3C'):
    """강조색 하나 → 진한·중간·옅은·아주 옅은 색."""
    a = hex_rgb(accent) if isinstance(accent, str) else accent
    h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in a])
    dark = tuple(int(v * 255) for v in colorsys.hls_to_rgb(h, max(0, l * 0.78), s))
    return {'accent': a, 'dark': dark, 'mid': _mix(a, WHITE, 0.28), 'light': _mix(a, WHITE, 0.55),
            'pale': _mix(a, WHITE, 0.88)}


# ------------------------------------------------------------------ 글꼴(운영체제마다 다른 한글 글꼴을 찾는다)
_FONT_CACHE = {}


def _font_dirs():
    dirs = []
    if sys.platform == 'win32':
        dirs += [os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts'),
                 os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')]
    elif sys.platform == 'darwin':
        dirs += [os.path.expanduser('~/Library/Fonts'), '/Library/Fonts', '/System/Library/Fonts',
                 '/System/Library/Fonts/Supplemental']
    else:
        dirs += [os.path.expanduser('~/.fonts'), os.path.expanduser('~/.local/share/fonts'), '/usr/share/fonts',
                 '/usr/local/share/fonts']
    return [d for d in dirs if d and os.path.isdir(d)]


def _find(patterns):
    for d in _font_dirs():
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, '**', pat), recursive=True))
            if hits:
                return hits[0]
    return None


FAMILIES = [
    # (이름, {굵기: 파일 패턴들})
    ('Pretendard', {'Regular': ['Pretendard-Regular.*'], 'SemiBold': ['Pretendard-SemiBold.*'],
                    'Bold': ['Pretendard-Bold.*']}),
    ('Malgun Gothic', {'Regular': ['malgun.ttf'], 'SemiBold': ['malgunbd.ttf'], 'Bold': ['malgunbd.ttf']}),
    ('Noto Sans KR', {'Regular': ['NotoSansKR-Regular.*', 'NotoSansKR*.ttf'], 'SemiBold': ['NotoSansKR-SemiBold.*', 'NotoSansKR-Bold.*'],
                      'Bold': ['NotoSansKR-Bold.*']}),
    ('Apple SD Gothic Neo', {'Regular': ['AppleSDGothicNeo.ttc'], 'SemiBold': ['AppleSDGothicNeo.ttc'],
                             'Bold': ['AppleSDGothicNeo.ttc']}),
    ('Nanum Gothic', {'Regular': ['NanumGothic.ttf'], 'SemiBold': ['NanumGothicBold.ttf'], 'Bold': ['NanumGothicBold.ttf']}),
    ('Noto Sans CJK', {'Regular': ['NotoSansCJK*-Regular.ttc', 'NotoSansCJK-Regular.ttc'],
                       'SemiBold': ['NotoSansCJK*-Bold.ttc'], 'Bold': ['NotoSansCJK*-Bold.ttc']}),
]
HANJA_FALLBACK = ['malgun.ttf', 'NotoSansKR-Regular.*', 'NotoSansCJK*-Regular.ttc', 'AppleSDGothicNeo.ttc', 'NanumGothic.ttf']


def font_files():
    """사용할 글꼴 파일 {'Regular': 경로, 'SemiBold': …, 'Bold': …, 'hanja': 경로, 'family': 이름}."""
    if 'files' in _FONT_CACHE:
        return _FONT_CACHE['files']
    res = None
    want = os.environ.get('HWPX_NEW_CHART_FONT')        # 직접 지정(파일 경로) 가능
    if want and os.path.exists(want):
        res = {'Regular': want, 'SemiBold': want, 'Bold': want, 'family': os.path.basename(want)}
    for fam, w in ([] if res else FAMILIES):
        reg = _find(w['Regular'])
        if reg:
            res = {'Regular': reg, 'SemiBold': _find(w['SemiBold']) or reg, 'Bold': _find(w['Bold']) or reg, 'family': fam}
            break
    if not res:
        raise RuntimeError('한글 글꼴을 찾지 못했습니다. 맑은 고딕·Pretendard·나눔고딕·Noto Sans KR 중 하나를 설치하거나 '
                           '환경변수 HWPX_NEW_CHART_FONT 에 글꼴 파일 경로를 지정하세요.')
    res['hanja'] = _find(HANJA_FALLBACK) or res['Regular']
    _FONT_CACHE['files'] = res
    return res


# ------------------------------------------------------------------ 그리기 판
class Canvas:
    def __init__(self, w, h, s=2):
        self.w, self.h, self.s = w, h, s
        self.im = Image.new('RGB', (int(w * s), int(h * s)), 'white')
        self.d = ImageDraw.Draw(self.im)
        self._fc = {}
        self.ff = font_files()

    def font(self, size, weight='Regular', hanja=False):
        key = (size, weight, hanja)
        if key not in self._fc:
            path = self.ff['hanja'] if hanja else self.ff.get(weight, self.ff['Regular'])
            self._fc[key] = ImageFont.truetype(path, int(size * self.s))
        return self._fc[key]

    @staticmethod
    def _runs(ln):
        out, cur, han = [], '', None
        for ch in ln:
            h = '一' <= ch <= '鿿'
            if han is None or h == han:
                cur += ch
            else:
                out.append((cur, han))
                cur = ch
            han = h
        if cur:
            out.append((cur, han))
        return out

    def _width_px(self, ln, size, weight):
        return sum(self.d.textlength(t, font=self.font(size, weight, h)) for t, h in self._runs(ln))

    def tw(self, txt, size=24, weight='Regular'):
        return max((self._width_px(ln, size, weight) if ln else 0) for ln in str(txt).split('\n')) / self.s

    def text(self, xy, txt, size=24, weight='Regular', fill=INK, anchor='la', spacing=1.32):
        x, y = xy
        lines = str(txt).split('\n')
        lh = size * spacing
        if anchor[1] == 'm':
            y -= lh * (len(lines) - 1) / 2
        elif anchor[1] in ('b', 'd', 's'):
            y -= lh * (len(lines) - 1)
        for i, ln in enumerate(lines):
            runs = self._runs(ln)
            total = sum(self.d.textlength(t, font=self.font(size, weight, h)) for t, h in runs)
            x0 = x * self.s - (total if anchor[0] == 'r' else total / 2 if anchor[0] == 'm' else 0)
            for t, h in runs:
                f = self.font(size, weight, h)
                self.d.text((x0, (y + i * lh) * self.s), t, font=f, fill=fill, anchor='l' + anchor[1])
                x0 += self.d.textlength(t, font=f)

    def line(self, pts, fill=INK, width=2, dash=None):
        pts = [(x * self.s, y * self.s) for x, y in pts]
        if not dash:
            self.d.line(pts, fill=fill, width=max(1, int(width * self.s)), joint='curve')
            return
        on, off = dash
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L == 0:
                continue
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            t = 0.0
            while t < L:
                t2 = min(L, t + on * self.s)
                self.d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * t2, y0 + uy * t2)], fill=fill,
                            width=max(1, int(width * self.s)))
                t = t2 + off * self.s

    def rect(self, box, fill=None, outline=None, width=0, radius=0):
        b = [v * self.s for v in box]
        if b[2] < b[0]:
            b[0], b[2] = b[2], b[0]
        if b[3] < b[1]:
            b[1], b[3] = b[3], b[1]
        if radius:
            self.d.rounded_rectangle(b, radius=radius * self.s, fill=fill, outline=outline, width=int(width * self.s))
        else:
            self.d.rectangle(b, fill=fill, outline=outline, width=int(width * self.s))

    def poly(self, pts, fill):
        self.d.polygon([(x * self.s, y * self.s) for x, y in pts], fill=fill)

    def dot(self, x, y, r, fill, ring=WHITE, ring_w=2.0):
        if ring:
            self.d.ellipse([(x - r - ring_w) * self.s, (y - r - ring_w) * self.s, (x + r + ring_w) * self.s,
                            (y + r + ring_w) * self.s], fill=ring)
        self.d.ellipse([(x - r) * self.s, (y - r) * self.s, (x + r) * self.s, (y + r) * self.s], fill=fill)

    def hollow(self, x, y, r, color, width=3):
        self.d.ellipse([(x - r) * self.s, (y - r) * self.s, (x + r) * self.s, (y + r) * self.s], fill=WHITE,
                       outline=color, width=int(width * self.s))

    def arrow(self, x0, y0, x1, y1, fill=MUTED, width=3, head=12):
        self.line([(x0, y0), (x1, y1)], fill=fill, width=width)
        ang = math.atan2(y1 - y0, x1 - x0)
        p1 = (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45))
        p2 = (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))
        self.poly([(x1, y1), p1, p2], fill)

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.im.save(path, dpi=(508, 508))
        return path


# ------------------------------------------------------------------ 도움 함수
def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '').replace('%', '')
    m = re.match(r'^[-+−]?\d+(\.\d+)?', s.replace('−', '-'))
    return float(m.group(0).replace('−', '-')) if m else None


def _ci(v):
    """'3.18[2.9,3.4]' → (3.18, 2.9, 3.4)."""
    m = re.match(r'^\s*([-\d.]+)\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]\s*$', str(v))
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    x = _num(v)
    return x, None, None


def _fmt(v, dec=None):
    if v is None:
        return ''
    if dec is None:
        dec = 0 if float(v).is_integer() else (1 if abs(v) >= 10 else 2)
    return f'{v:.{dec}f}'


def _nice_max(v):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * e >= v * 1.08:
            return m * e
    return 10 * e


def _step(lo, hi, n=5):
    raw = (hi - lo) / n
    e = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return min((m * e for m in (1, 2, 5, 10) if m * e >= raw), default=raw or 1)


def _ticks(lo, hi, n=5):
    """lo~hi 안의 '단계의 배수' 눈금(0·5·10, 1·2·3 …). 축 끝이 배수가 아니어도 어색한 값(−1, 4, 9)을 쓰지 않는다."""
    step = _step(lo, hi, n)
    k = math.ceil(lo / step - 1e-9)
    out = []
    while k * step <= hi + 1e-9:
        out.append(round(k * step, 6))
        k += 1
    return out or [lo, hi]


def _snap(lo, hi, n=5):
    """축 범위를 눈금 단계의 배수로 넓힌다(산점도처럼 자료에서 범위를 정할 때)."""
    step = _step(lo, hi, n)
    return math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step


def _legend(c, x, y, items, size=22, box=20, gap=26):
    for col, lab in items:
        c.rect((x, y - box / 2, x + box, y + box / 2), fill=col, radius=4)
        c.text((x + box + 9, y), lab, size=size, fill=BODY, anchor='lm')
        x += box + 9 + c.tw(lab, size) + gap
    return x


def _hl(spec, rows):
    h = spec.get('highlight')
    if h is None or h == '':
        return set()
    if isinstance(h, (int, float)):
        h = [h]
    if isinstance(h, str):
        h = [x.strip() for x in h.split(',') if x.strip()]
    out = set()
    for x in h:
        if str(x).lstrip('-').isdigit():
            i = int(x)
            out.add(i - 1 if i > 0 else len(rows) + i)
        elif x in ('max', 'min'):
            vals = [_num(r[1]) for r in rows]
            out.add(vals.index(max(vals) if x == 'max' else min(vals)))
        else:
            out |= {i for i, r in enumerate(rows) if str(r[0]) == x}
    return out


def _series_colors(pal, n):
    base = [PRE, pal['accent'], pal['mid'], pal['dark'], pal['light']]
    return (base * 3)[:n]


def _seq_colors(pal, n):
    ramp = [pal['pale'], pal['light'], pal['mid'], pal['accent'], pal['dark']]
    if n <= 1:
        return [pal['accent']]
    idx = [round(i * (len(ramp) - 1) / (n - 1)) for i in range(n)]
    return [ramp[i] for i in idx]


def _head(c, spec, x=40, y=34):
    lab = spec.get('label') or ''
    if spec.get('unit') and spec.get('type') in ('bar', 'hist', 'group', 'line') and '단위' not in lab:
        lab = (lab + '  ' if lab else '') + f"(단위: {spec['unit']})"
    if lab:
        c.text((x, y), lab, size=25, weight='SemiBold', fill=INK, anchor='la')


def _note(c, spec, y):
    if spec.get('note'):
        c.text((40, y), spec['note'], size=19, fill=MUTED, anchor='la')


# ------------------------------------------------------------------ 종류별 그리기
def _bar(spec, pal, horizontal=False):
    rows = spec['rows']
    vals = [_num(r[1]) for r in rows]
    W = spec.get('width', DEFAULT_W)
    hl = _hl(spec, rows)
    unit = spec.get('unit', '')
    dec = spec.get('decimals')
    lo = float(spec.get('min', 0))
    hi = float(spec.get('max') or _nice_max(max(vals)))
    if not horizontal:
        H = int(spec.get('height', 560))
        c = Canvas(W, H)
        _head(c, spec)
        x0, x1, yt, yb = 110, W - 40, 110, H - 100
        for v in _ticks(lo, hi):
            y = yb - (yb - yt) * (v - lo) / (hi - lo)
            c.line([(x0, y), (x1, y)], fill=FAINT if v == lo else GRID, width=2)
            c.text((x0 - 14, y), _fmt(v, 0 if hi >= 10 else 1), size=19, fill=MUTED, anchor='rm')
        n = len(rows)
        slot = (x1 - x0) / n
        bw = min(110, slot * (0.86 if spec.get('type') == 'hist' else 0.62))
        for i, (r, v) in enumerate(zip(rows, vals)):
            cx = x0 + slot * (i + 0.5)
            y = yb - (yb - yt) * (v - lo) / (hi - lo)
            col = pal['accent'] if (not hl or i in hl) else pal['light']
            c.rect((cx - bw / 2, y, cx + bw / 2, yb), fill=col, radius=5)
            c.rect((cx - bw / 2, yb - 6, cx + bw / 2, yb), fill=col)
            c.text((cx, y - 10), _fmt(v, dec) + ('' if spec.get('type') == 'hist' else ''), size=21,
                   weight='Bold' if (not hl or i in hl) else 'Regular', fill=pal['dark'] if (not hl or i in hl) else BODY,
                   anchor='mb')
            c.text((cx, yb + 28), str(r[0]).replace('/', '\n'), size=20, fill=INK, anchor='ma')
        _note(c, spec, H - 34)
        return c
    n = len(rows)
    rh = 54
    H = int(spec.get('height', 110 + n * rh + 60))
    c = Canvas(W, H)
    _head(c, spec)
    lab_w = max(c.tw(str(r[0]), 22) for r in rows) + 30
    x0 = max(260, min(700, lab_w + 40))
    x1 = W - 120
    top = 96
    for v in _ticks(lo, hi):
        x = x0 + (x1 - x0) * (v - lo) / (hi - lo)
        c.line([(x, top - 10), (x, top + n * rh)], fill=FAINT if v == lo else GRID, width=2)
        c.text((x, top + n * rh + 24), _fmt(v, 0 if hi >= 10 else 1), size=19, fill=MUTED, anchor='mm')
    for i, (r, v) in enumerate(zip(rows, vals)):
        y = top + rh * i + rh / 2
        c.text((x0 - 16, y), str(r[0]), size=22, weight='SemiBold' if (hl and i in hl) else 'Regular',
               fill=pal['accent'] if (hl and i in hl) else INK, anchor='rm')
        xv = x0 + (x1 - x0) * (v - lo) / (hi - lo)
        col = pal['accent'] if (not hl or i in hl) else pal['light']
        c.rect((x0, y - 15, xv, y + 15), fill=col, radius=5)
        c.rect((x0, y - 15, x0 + 6, y + 15), fill=col)
        c.text((xv + 12, y), _fmt(v, dec) + unit, size=21, weight='Bold', fill=pal['dark'] if (not hl or i in hl) else BODY,
               anchor='lm')
    _note(c, spec, H - 30)
    return c


def _group(spec, pal):
    rows = spec['rows']
    legend = spec.get('legend') or [f'계열 {i + 1}' for i in range(len(rows[0]) - 1)]
    ns = len(rows[0]) - 1
    cols = _series_colors(pal, ns)
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 560))
    c = Canvas(W, H)
    _head(c, spec)
    _legend(c, W - 40 - sum(c.tw(l, 22) + 55 for l in legend), 36, list(zip(cols, legend)))
    vals = [[_ci(v) for v in r[1:]] for r in rows]
    allv = [v for row in vals for (m, lo_, hi_) in row for v in (m, hi_) if v is not None]
    lo = float(spec.get('min', 0))
    hi = float(spec.get('max') or _nice_max(max(allv)))
    x0, x1, yt, yb = 110, W - 40, 100, H - 90
    for v in _ticks(lo, hi):
        y = yb - (yb - yt) * (v - lo) / (hi - lo)
        c.line([(x0, y), (x1, y)], fill=FAINT if v == lo else GRID, width=2)
        c.text((x0 - 14, y), _fmt(v, 0 if hi >= 10 else 1), size=19, fill=MUTED, anchor='rm')
    slot = (x1 - x0) / len(rows)
    bw = min(100, slot * 0.8 / ns)
    dec = spec.get('decimals')
    for i, r in enumerate(rows):
        cx = x0 + slot * (i + 0.5)
        for k, (m, l_, h_) in enumerate(vals[i]):
            bx = cx - bw * ns / 2 + k * bw + 4
            y = yb - (yb - yt) * (m - lo) / (hi - lo)
            c.rect((bx, y, bx + bw - 8, yb), fill=cols[k], radius=5)
            c.rect((bx, yb - 6, bx + bw - 8, yb), fill=cols[k])
            ytxt = y
            if l_ is not None:
                yl, yh = yb - (yb - yt) * (l_ - lo) / (hi - lo), yb - (yb - yt) * (h_ - lo) / (hi - lo)
                xm = bx + (bw - 8) / 2
                c.line([(xm, yh), (xm, yl)], fill=INK, width=3)
                c.line([(xm - 12, yh), (xm + 12, yh)], fill=INK, width=3)
                c.line([(xm - 12, yl), (xm + 12, yl)], fill=INK, width=3)
                ytxt = yh
            c.text((bx + (bw - 8) / 2, ytxt - 10), _fmt(m, dec), size=20, weight='Bold' if k == ns - 1 else 'Regular',
                   fill=pal['dark'] if k == ns - 1 else BODY, anchor='mb')
        c.text((cx, yb + 28), str(r[0]).replace('/', '\n'), size=21, fill=INK, anchor='ma')
    _note(c, spec, H - 30)
    return c


def _dumbbell(spec, pal):
    rows = spec['rows']
    legend = spec.get('legend') or ['사전', '사후']
    n = len(rows)
    rh = 74
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 120 + n * rh + 70))
    c = Canvas(W, H)
    _head(c, spec)
    extra = any(len(r) > 3 and str(r[3]).strip() for r in rows)
    lab_w = max(c.tw(str(r[0]), 23, 'SemiBold') for r in rows)
    x0 = max(260, min(620, lab_w + 60))
    x1 = W - (260 if extra else 80)
    vals = [(_num(r[1]), _num(r[2])) for r in rows]
    lo = float(spec.get('min', 1))
    hi = float(spec.get('max', 5))
    top = 110
    _legend(c, W - 40 - sum(c.tw(l, 22) + 55 for l in legend[:2]), 36, [(PRE, legend[0]), (pal['accent'], legend[1])])
    for v in _ticks(lo, hi, int(hi - lo) if (hi - lo) <= 8 else 5):
        x = x0 + (x1 - x0) * (v - lo) / (hi - lo)
        c.line([(x, top - 8), (x, top + n * rh)], fill=GRID, width=2)
        c.text((x, top + n * rh + 24), _fmt(v, 0 if float(v).is_integer() else 1), size=19, fill=MUTED, anchor='mm')
    if extra and spec.get('extra_label'):
        c.text(((x1 + W) / 2 + 20, top - 30), spec['extra_label'], size=20, weight='SemiBold', fill=MUTED, anchor='mm')
    dec = spec.get('decimals', 2)
    for i, (r, (a, b)) in enumerate(zip(rows, vals)):
        y = top + rh * i + rh / 2
        c.text((x0 - 20, y), str(r[0]), size=23, weight='SemiBold', fill=INK, anchor='rm')
        xa, xb = x0 + (x1 - x0) * (a - lo) / (hi - lo), x0 + (x1 - x0) * (b - lo) / (hi - lo)
        c.line([(xa, y), (xb, y)], fill=pal['light'], width=8)
        c.dot(xa, y, 12, PRE)
        c.dot(xb, y, 13, pal['accent'])
        left, right = (xa, xb) if xa <= xb else (xb, xa)
        c.text((left - 18, y), _fmt(a if xa <= xb else b, dec), size=20, fill=MUTED if xa <= xb else pal['dark'], anchor='rm')
        c.text((right + 18, y), _fmt(b if xa <= xb else a, dec), size=21, weight='Bold', fill=pal['dark'] if xa <= xb else MUTED,
               anchor='lm')
        if extra and len(r) > 3:
            t = str(r[3])
            hot = (_num(t) or 0) >= float(spec.get('hot', 0.8))
            cx = (x1 + W) / 2 + 20
            c.rect((cx - 66, y - 22, cx + 66, y + 22), fill=pal['accent'] if hot else pal['pale'], radius=22)
            c.text((cx, y), t, size=21, weight='Bold', fill=WHITE if hot else pal['accent'], anchor='mm')
    _note(c, spec, H - 30)
    return c


def _stack(spec, pal):
    rows = spec['rows']
    ncat = len(rows[0]) - 1
    legend = spec.get('legend') or [f'{i + 1}' for i in range(ncat)]
    cols = _seq_colors(pal, ncat)
    n = len(rows)
    rh = 70
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 150 + n * rh + 40))
    c = Canvas(W, H)
    _head(c, spec)
    lab_w = max(c.tw(str(r[0]), 22, 'SemiBold') for r in rows)
    x0 = max(170, min(520, lab_w + 50))
    x1 = W - 40
    top = 120 if spec.get('label') else 90
    _legend(c, x0, top - 40, list(zip(cols, legend)))
    for i, r in enumerate(rows):
        vals = [_num(v) or 0 for v in r[1:]]
        tot = sum(vals) or 1
        y = top + rh * i + rh / 2
        c.text((x0 - 18, y), str(r[0]), size=22, weight='SemiBold', fill=INK, anchor='rm')
        x = x0
        for k, v in enumerate(vals):
            w = (x1 - x0) * v / tot
            c.rect((x, y - 22, x + w - 2, y + 22), fill=cols[k])
            if w > 64:
                dark_bg = k >= ncat / 2
                c.text((x + w / 2, y), _fmt(v, spec.get('decimals', 1)), size=20, weight='SemiBold',
                       fill=WHITE if dark_bg else INK, anchor='mm')
            x += w
    _note(c, spec, H - 30)
    return c


def _effect(spec, pal):
    rows = spec['rows']
    n = len(rows)
    rh = 58
    W = spec.get('width', DEFAULT_W)
    groups = [str(r[3]).strip() if len(r) > 3 else '' for r in rows]
    has_group = any(groups)
    H = int(spec.get('height', 120 + n * rh + 110))
    c = Canvas(W, H)
    _head(c, spec)
    vals = [_num(r[1]) for r in rows]
    lo, hi = float(spec.get('min', 0)), float(spec.get('max') or max(1.6, _nice_max(max(vals))))
    lab_w = max(c.tw(str(r[0]), 23, 'SemiBold') for r in rows)
    x0 = (250 if has_group else 60) + lab_w + 30
    x1 = W - 180
    top = 120
    X = lambda v: x0 + (x1 - x0) * (v - lo) / (hi - lo)  # noqa: E731
    ybot = top + rh * n + 20
    for v in _ticks(lo, hi, 4):
        c.line([(X(v), top - 10), (X(v), ybot)], fill=GRID, width=2)
        c.text((X(v), ybot + 24), _fmt(v, 1), size=19, fill=MUTED, anchor='mm')
    for v, lab in ((0.2, '작은 0.2'), (0.5, '중간 0.5'), (0.8, '큰 0.8')):
        if lo <= v <= hi:
            c.line([(X(v), top - 14), (X(v), ybot)], fill=pal['light'], width=2, dash=(8, 6))
            c.text((X(v), top - 32), lab, size=19, weight='SemiBold', fill=pal['mid'], anchor='mm')
    prev = None
    for i, (r, v) in enumerate(zip(rows, vals)):
        y = top + rh * i + rh / 2
        if has_group and groups[i] != prev:
            c.text((40, y), groups[i], size=21, weight='Bold', fill=pal['accent'], anchor='lm')
            if prev is not None:
                c.line([(40, y - rh / 2), (x1, y - rh / 2)], fill=PRE_L, width=2)
            prev = groups[i]
        note = str(r[2]).strip() if len(r) > 2 else ''
        c.text((x0 - 16, y - (8 if note else 0)), str(r[0]), size=22, weight='SemiBold', fill=INK, anchor='rm')
        if note:
            c.text((x0 - 16, y + 17), note, size=16, fill=MUTED, anchor='rm')
        col = pal['accent'] if v >= 0.8 else (pal['mid'] if v >= 0.5 else pal['light'])
        c.rect((X(lo), y - 15, X(v), y + 15), fill=col, radius=5)
        c.rect((X(lo), y - 15, X(lo) + 6, y + 15), fill=col)
        lab = _fmt(v, 2)
        c.rect((X(v) + 6, y - 16, X(v) + 18 + c.tw(lab, 21, 'Bold'), y + 16), fill=WHITE)
        c.text((X(v) + 12, y), lab, size=21, weight='Bold', fill=pal['dark'] if v >= 0.5 else BODY, anchor='lm')
    c.text((x1 + 150, H - 22), spec.get('note') or '기준: Cohen(1988) 0.2 작은 · 0.5 중간 · 0.8 큰 효과', size=18,
           fill=MUTED, anchor='rd')
    return c


def _scatter(spec, pal):
    pts = [(_num(r[0]), _num(r[1])) for r in spec['rows'] if _num(r[0]) is not None and _num(r[1]) is not None]
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 620))
    c = Canvas(W, H)
    _head(c, spec)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    sx = _snap(min(0, min(xs)), max(xs) if max(xs) > min(0, min(xs)) else max(xs) + 1, 5)
    xlo = float(spec.get('xmin', sx[0]))
    xhi = float(spec.get('xmax', sx[1]))
    span = (max(ys) - min(ys)) or 1
    sy = _snap(min(ys) - span * 0.08, max(ys) + span * 0.08, 6)
    ylo = float(spec.get('ymin', sy[0]))
    yhi = float(spec.get('ymax', sy[1]))
    x0, x1, yt, yb = 140, W - 60, (140 if spec.get('label') else 100), H - 120
    X = lambda v: x0 + (x1 - x0) * (v - xlo) / (xhi - xlo)  # noqa: E731
    Y = lambda v: yb - (yb - yt) * (v - ylo) / (yhi - ylo)  # noqa: E731
    for v in _ticks(ylo, yhi, 6):
        c.line([(x0, Y(v)), (x1, Y(v))], fill=FAINT if abs(v) < 1e-9 else GRID, width=2)
        c.text((x0 - 14, Y(v)), _fmt(v, 1), size=19, fill=MUTED, anchor='rm')
    for v in _ticks(xlo, xhi, 5):
        c.text((X(v), yb + 26), _fmt(v, 0 if float(v).is_integer() else 1), size=19, fill=MUTED, anchor='mm')
    if spec.get('xlabel'):
        c.text(((x0 + x1) / 2, yb + 62), spec['xlabel'], size=21, fill=BODY, anchor='mm')
    if spec.get('ylabel'):
        c.text((x0 - 100, yt - 48), spec['ylabel'], size=20, weight='SemiBold', fill=BODY, anchor='la')
    seen = {}
    for a, b in pts:
        k = (round(a, 3), round(b, 3))
        j = seen.get(k, 0)
        seen[k] = j + 1
        c.dot(X(a) + j * 8, Y(b), 7.5, pal['mid'], ring=WHITE, ring_w=1.5)
    from .stats import pearson, nolead, rd, fmt_p
    if spec.get('fit', True) and len(pts) > 2:
        pr = pearson(xs, ys)
        xa, xb = min(xs), max(xs)
        c.line([(X(xa), Y(pr['intercept'] + pr['slope'] * xa)), (X(xb), Y(pr['intercept'] + pr['slope'] * xb))],
               fill=pal['dark'], width=4)
        lab = f"r = {nolead(rd(pr['r']))}, p {fmt_p(pr['p'])}, n = {pr['n']}"
        c.rect((x0 + 14, yt - 2, x0 + 30 + c.tw(lab, 23, 'Bold'), yt + 42), fill=WHITE)
        c.text((x0 + 22, yt + 20), lab, size=23, weight='Bold', fill=pal['accent'], anchor='lm')
    _note(c, spec, H - 30)
    return c


def _line(spec, pal):
    rows = spec['rows']
    ns = len(rows[0]) - 1
    legend = spec.get('legend') or [f'계열 {i + 1}' for i in range(ns)]
    cols = ([pal['accent'], PRE, pal['mid'], pal['dark'], pal['light']] * 2)[:ns] if ns > 1 else [pal['accent']]   # 첫 계열(우리 학교)이 강조색
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 560))
    c = Canvas(W, H)
    _head(c, spec)
    if ns > 1:
        _legend(c, W - 40 - sum(c.tw(l, 22) + 55 for l in legend), 36, list(zip(cols, legend)))
    vals = [[_num(v) for v in r[1:]] for r in rows]
    allv = [v for r in vals for v in r if v is not None]
    lo = float(spec.get('min', 0))
    hi = float(spec.get('max') or _nice_max(max(allv)))
    x0, x1, yt, yb = 110, W - 60, 100, H - 90
    for v in _ticks(lo, hi):
        y = yb - (yb - yt) * (v - lo) / (hi - lo)
        c.line([(x0, y), (x1, y)], fill=FAINT if v == lo else GRID, width=2)
        c.text((x0 - 14, y), _fmt(v, 0 if hi >= 10 else 1), size=19, fill=MUTED, anchor='rm')
    n = len(rows)
    step = (x1 - x0) / max(1, n - 1) if n > 1 else 0
    X = lambda i: x0 + step * i if n > 1 else (x0 + x1) / 2  # noqa: E731
    Y = lambda v: yb - (yb - yt) * (v - lo) / (hi - lo)  # noqa: E731
    for i, r in enumerate(rows):
        c.text((X(i), yb + 28), str(r[0]), size=20, fill=INK, anchor='ma')
    for k in range(ns):
        pts = [(X(i), Y(vals[i][k])) for i in range(n) if vals[i][k] is not None]
        c.line(pts, fill=cols[k], width=5)
        for (x, y), i in zip(pts, range(n)):
            c.dot(x, y, 8, cols[k])
        if pts:
            c.text((pts[-1][0] + 14, pts[-1][1]), _fmt(vals[n - 1][k], spec.get('decimals')), size=21, weight='Bold',
                   fill=pal['accent'] if k == 0 else BODY, anchor='lm')
    _note(c, spec, H - 30)
    return c


def _timeline(spec, pal):
    rows = spec['rows']
    n = len(rows)
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 450))
    c = Canvas(W, H)
    _head(c, spec)
    hl = _hl(spec, rows)
    y = 190
    x0, x1 = 170, W - 170
    done_last = max([i for i, r in enumerate(rows) if not (len(r) > 2 and str(r[2]).strip().lower() in ('no', 'todo', '예정'))]
                    or [0])
    c.line([(x0 - 60, y), (x1 + 60, y)], fill=PRE_L, width=8)
    c.line([(x0 - 60, y), (x0 + (x1 - x0) * done_last / max(1, n - 1), y)], fill=pal['light'], width=8)
    for i, r in enumerate(rows):
        x = x0 + (x1 - x0) * i / max(1, n - 1)
        todo = len(r) > 2 and str(r[2]).strip().lower() in ('no', 'todo', '예정')
        if i in hl:
            c.dot(x, y, 26, pal['accent'], ring=WHITE, ring_w=5)
        elif todo:
            c.hollow(x, y, 18, pal['mid'], width=5)
        else:
            c.dot(x, y, 18, pal['mid'], ring=WHITE, ring_w=4)
        c.text((x, y - 70), str(r[0]), size=31, weight='Bold', fill=pal['accent'] if i in hl else INK, anchor='mm')
        for k, ln in enumerate(str(r[1]).split('/')):
            c.text((x, y + 70 + k * 38), ln.strip(), size=24, weight='SemiBold' if i in hl else 'Regular',
                   fill=pal['accent'] if i in hl else BODY, anchor='mm')
    _note(c, spec, H - 30)
    return c


def _steps(spec, pal):
    rows = spec['rows']
    n = len(rows)
    W = spec.get('width', DEFAULT_W)
    top = 70 if spec.get('label') else 30
    H = int(spec.get('height', top + 230 + (70 if spec.get('note') else 30)))
    c = Canvas(W, H)
    _head(c, spec)
    gap = 44
    w = (W - 40 - gap * (n - 1)) / n
    for i, r in enumerate(rows):
        x0 = 20 + i * (w + gap)
        c.rect((x0, top, x0 + w, top + 230), fill=pal['pale'] if i % 2 == 0 else PAPER, radius=14)
        c.dot(x0 + 34, top + 38, 20, pal['accent'], ring=None)
        c.text((x0 + 34, top + 38), str(i + 1), size=22, weight='Bold', fill=WHITE, anchor='mm')
        c.text((x0 + 64, top + 38), str(r[0]), size=24, weight='Bold', fill=INK, anchor='lm')
        if len(r) > 1 and str(r[1]).strip():
            c.text((x0 + w / 2, top + 88), str(r[1]), size=21, weight='SemiBold', fill=pal['accent'], anchor='mm')
        if len(r) > 2:
            c.text((x0 + w / 2, top + 160), '\n'.join(s.strip() for s in str(r[2]).split('/')), size=20, fill=BODY, anchor='mm')
        if i < n - 1:
            c.arrow(x0 + w + 6, top + 115, x0 + w + gap - 6, top + 115, fill=pal['mid'], width=5, head=14)
    _note(c, spec, H - 30)
    return c


def _cycle(spec, pal):
    rows = spec['rows'][:6]
    n = len(rows)
    W = spec.get('width', DEFAULT_W)
    H = int(spec.get('height', 760))
    c = Canvas(W, H)
    _head(c, spec)
    cx, cy = W / 2, H / 2 + 10
    rx, ry = W * 0.33, H * 0.34
    c.dot(cx, cy, 90, pal['pale'], ring=None)
    c.text((cx, cy), str(spec.get('center', '')).replace('/', '\n'), size=28, weight='Bold', fill=pal['accent'], anchor='mm')
    pos = []
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        pos.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
    bw, bh = 400, 170

    def edge(ax, ay, bx, by, pad=16):
        dx, dy = bx - ax, by - ay
        t = min((bw / 2) / abs(dx) if dx else 1e9, (bh / 2) / abs(dy) if dy else 1e9)
        L = math.hypot(dx, dy) or 1
        return ax + dx * t + dx / L * pad, ay + dy * t + dy / L * pad
    for i in range(n):
        (xa, ya), (xb, yb) = pos[i], pos[(i + 1) % n]
        sx, sy = edge(xa, ya, xb, yb)
        ex, ey = edge(xb, yb, xa, ya)
        c.arrow(sx, sy, ex, ey, fill=pal['mid'], width=4, head=16)
    for (x, y), r in zip(pos, rows):
        c.rect((x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2), fill=WHITE, outline=pal['accent'], width=2, radius=14)
        c.text((x, y - 44), str(r[0]), size=26, weight='Bold', fill=pal['accent'], anchor='mm')
        if len(r) > 1:
            c.text((x, y + 22), '\n'.join(s.strip() for s in str(r[1]).split('/')), size=21, fill=BODY, anchor='mm')
    _note(c, spec, H - 30)
    return c


TYPES = {'bar': lambda s, p: _bar(s, p), 'hist': lambda s, p: _bar(s, p), 'hbar': lambda s, p: _bar(s, p, True),
         'group': _group, 'dumbbell': _dumbbell, 'stack': _stack, 'effect': _effect, 'scatter': _scatter, 'line': _line,
         'timeline': _timeline, 'steps': _steps, 'cycle': _cycle}


def normalize(spec):
    """옵션 정리: legend 쉼표 문자열 → 목록, 숫자 문자열 → 수."""
    s = dict(spec)
    for k in ('legend',):
        if isinstance(s.get(k), str):
            s[k] = [x.strip() for x in s[k].split(',')]
    for k in ('min', 'max', 'xmin', 'xmax', 'ymin', 'ymax', 'width', 'height', 'decimals', 'hot'):
        if isinstance(s.get(k), str) and s[k].strip():
            v = _num(s[k])
            s[k] = int(v) if k in ('width', 'height', 'decimals') else v
    if isinstance(s.get('fit'), str):
        s['fit'] = s['fit'].strip().lower() not in ('0', 'no', 'false', '아니오')
    rows = []
    for r in s.get('rows') or []:
        if isinstance(r, str):
            r = [x.strip() for x in r.split('|')]
        rows.append(list(r))
    s['rows'] = rows
    return s


def render(spec, out, accent=None):
    """spec(dict·JSON 문자열·JSON 파일 경로) → PNG 경로."""
    if isinstance(spec, str):
        spec = json.load(open(spec, encoding='utf-8')) if os.path.exists(spec) else json.loads(spec)
    s = normalize(spec)
    kind = s.get('type', 'bar')
    s['type'] = kind
    if kind not in TYPES:
        raise ValueError(f'알 수 없는 도표 종류: {kind} (쓸 수 있는 것: {", ".join(TYPES)})')
    if not s['rows']:
        raise ValueError('도표 자료(rows)가 없습니다.')
    pal = palette(s.get('accent') or accent or '#8C1C3C')
    c = TYPES[kind](s, pal)
    return c.save(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='hwpx-new chart', description='도표 명세(JSON) → PNG (보고서와 같은 디자인)')
    ap.add_argument('spec', help='도표 명세 JSON 파일(또는 JSON 문자열)')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--accent', help='강조색(#RRGGBB)')
    a = ap.parse_args(argv)
    print(render(a.spec, a.out, a.accent))
    return 0


if __name__ == '__main__':
    sys.exit(main())
