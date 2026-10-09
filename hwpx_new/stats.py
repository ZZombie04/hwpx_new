# -*- coding: utf-8 -*-
"""보고서용 기본 통계 — 외부 패키지 없이(표준 라이브러리만) 계산한다. AI 가 머릿속으로 계산하지 않게 하려는 도구.

- paired(사전, 사후): 짝지은 t검정, 효과 크기 d(dz = 평균 변화 ÷ 변화의 표준편차, dav = 평균 변화 ÷ 두 표준편차 평균),
  변화량 95% 신뢰구간, 오른·같은·내린 사람 수, 사전·사후 상관
- welch(가, 나): 두 독립 집단 Welch t검정(분산이 같다고 가정하지 않음), 효과 크기 Hedges' g
- cronbach(문항 응답 행렬): 신뢰도 α
- kappa(평정자1, 평정자2): 가중 카파(선형/제곱), 완전 일치율
- pearson(x, y): 상관 r 과 p
- describe(값): n·평균·표준편차·가운데값·범위 / freq(값, 집단): 빈도와 비율(%)
- fmt_p(.0004) → '< .001', fmt_p(.023) → '= .023' (APA: 1을 넘지 않는 값은 앞의 0을 뺌)

명령줄: hwpx-new stats paired 자료.csv --pre 사전 --post 사후 [--prefix ref] [--where 경력=초임]
결과 끝의 '@set …' 줄을 보고서 원고에 붙여 넣으면 본문에서 {{ref.t}} 처럼 쓸 수 있다(숫자를 손으로 옮겨 적지 않음).
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from decimal import Decimal, ROUND_HALF_UP


# ------------------------------------------------------------------ 반올림·표기
def rd(v, nd=2):
    """사사오입(0.125 → 0.13). 파이썬 round 의 은행가 반올림을 쓰지 않는다."""
    q = Decimal(1).scaleb(-nd)
    return str(Decimal(str(round(float(v), 10))).quantize(q, ROUND_HALF_UP))


def nolead(s):
    """.87처럼 1을 넘지 않는 값(α, p, r, κ)은 앞의 0을 뺀다."""
    s = str(s)
    if s.startswith('0.'):
        return s[1:]
    if s.startswith('-0.'):
        return '-' + s[2:]
    return s


def fmt_p(p):
    return '< .001' if p < .001 else '= ' + nolead(rd(p, 3))


def effect_label(d):
    """Cohen(1988): 0.2 작은, 0.5 중간, 0.8 큰 효과."""
    d = abs(d)
    return '큰' if d >= .8 else ('중간' if d >= .5 else ('작은' if d >= .2 else '매우 작은'))


# ------------------------------------------------------------------ 분포 함수(불완전 베타)
def _betacf(a, b, x):
    mx, eps, fpmin = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = fpmin if abs(d) < fpmin else d
    d = 1.0 / d
    h = d
    for m in range(1, mx + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betai(a, b, x):
    """정칙화 불완전 베타 함수 I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    bt = math.exp(lbt)
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_p_two(t, df):
    """t 분포 양측 p 값."""
    if df <= 0:
        return float('nan')
    return betai(df / 2.0, 0.5, df / (df + t * t))


def t_crit(df, conf=.95):
    """양측 신뢰수준 conf 의 t 임계값(예: df=61 → 1.9996)."""
    alpha = 1 - conf
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_p_two(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ------------------------------------------------------------------ 기본
def _nums(xs):
    out = []
    for x in xs:
        if x is None:
            continue
        if isinstance(x, str):
            x = x.strip()
            if not x:
                continue
        out.append(float(x))
    return out


def mean(xs):
    xs = _nums(xs)
    return sum(xs) / len(xs)


def sd(xs):
    xs = _nums(xs)
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0


def _pairs(a, b):
    pa, pb = [], []
    for x, y in zip(a, b):
        if x in (None, '') or y in (None, ''):
            continue
        pa.append(float(x))
        pb.append(float(y))
    return pa, pb


# ------------------------------------------------------------------ 검정
def pearson(x, y):
    x, y = _pairs(x, y)
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0
    t = r * math.sqrt((n - 2) / max(1e-300, 1 - r * r)) if n > 2 else 0.0
    return {'n': n, 'r': r, 'p': t_p_two(t, n - 2) if n > 2 else float('nan'), 'df': n - 2,
            'slope': sxy / sxx if sxx else 0.0, 'intercept': my - (sxy / sxx if sxx else 0.0) * mx}


def paired(pre, post, conf=.95):
    """짝지은 t검정(같은 사람의 사전·사후)."""
    a, b = _pairs(pre, post)
    n = len(a)
    if n < 2:
        raise ValueError('짝지은 자료가 2쌍 이상 필요합니다.')
    d = [y - x for x, y in zip(a, b)]
    md, sdd = sum(d) / n, sd(d)
    m0, m1, s0, s1 = mean(a), mean(b), sd(a), sd(b)
    se = sdd / math.sqrt(n)
    t = md / se if se else float('inf')
    tc = t_crit(n - 1, conf)
    return {'test': 'paired', 'n': n, 'm0': m0, 's0': s0, 'm1': m1, 's1': s1, 'diff': md, 'sd_diff': sdd,
            't': t, 'df': n - 1, 'p': t_p_two(t, n - 1) if se else 0.0,
            'dz': md / sdd if sdd else float('inf'), 'dav': md / ((s0 + s1) / 2) if (s0 + s1) else float('inf'),
            'ci_lo': md - tc * se, 'ci_hi': md + tc * se, 'conf': conf,
            'up': sum(1 for x in d if x > 0), 'same': sum(1 for x in d if x == 0), 'down': sum(1 for x in d if x < 0),
            'r': pearson(a, b)['r']}


def welch(g0, g1, conf=.95):
    """두 독립 집단 Welch t검정(예: 익명 학생 설문 4월 vs 10월). 효과 크기 Hedges' g."""
    a, b = _nums(g0), _nums(g1)
    n0, n1 = len(a), len(b)
    m0, m1, s0, s1 = mean(a), mean(b), sd(a), sd(b)
    v0, v1 = s0 * s0 / n0, s1 * s1 / n1
    se = math.sqrt(v0 + v1)
    t = (m1 - m0) / se if se else float('inf')
    df = (v0 + v1) ** 2 / (v0 * v0 / (n0 - 1) + v1 * v1 / (n1 - 1)) if (v0 + v1) else float('inf')
    sp = math.sqrt(((n0 - 1) * s0 * s0 + (n1 - 1) * s1 * s1) / (n0 + n1 - 2))
    dd = (m1 - m0) / sp if sp else float('inf')
    j = 1 - 3 / (4 * (n0 + n1) - 9)
    tc = t_crit(df, conf)
    return {'test': 'welch', 'n0': n0, 'n1': n1, 'm0': m0, 's0': s0, 'm1': m1, 's1': s1, 'diff': m1 - m0,
            't': t, 'df': df, 'p': t_p_two(t, df), 'd': dd, 'g': dd * j,
            'ci_lo': (m1 - m0) - tc * se, 'ci_hi': (m1 - m0) + tc * se, 'conf': conf}


def cronbach(rows):
    """rows: 응답자별 [문항1, 문항2, …] (빈칸이 있는 응답자는 뺀다)."""
    data = [[float(v) for v in r] for r in rows if r and all(v not in (None, '') for v in r)]
    k = len(data[0])
    if k < 2:
        raise ValueError('문항이 2개 이상 필요합니다.')
    cols = list(zip(*data))
    item_var = sum(sd(c) ** 2 for c in cols)
    total_var = sd([sum(r) for r in data]) ** 2
    return {'k': k, 'n': len(data), 'alpha': k / (k - 1) * (1 - item_var / total_var) if total_var else float('nan')}


def kappa(r1, r2, weights='linear', categories=None):
    """가중 카파: weights='linear'(순서 범주 기본) | 'quadratic' | None(단순 카파)."""
    a, b = [], []
    for x, y in zip(r1, r2):
        if x in (None, '') or y in (None, ''):
            continue
        a.append(str(x).strip())
        b.append(str(y).strip())
    cats = categories or sorted(set(a) | set(b), key=lambda v: (float(v) if _isnum(v) else 0, v))
    idx = {c: i for i, c in enumerate(cats)}
    k, n = len(cats), len(a)
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[idx[x]][idx[y]] += 1
    row = [sum(r) for r in obs]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights == 'quadratic':
            return ((i - j) / (k - 1)) ** 2 if k > 1 else 0
        if weights == 'linear':
            return abs(i - j) / (k - 1) if k > 1 else 0
        return 0 if i == j else 1
    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    kap = 1 - po / pe if pe else 1.0
    return {'n': n, 'kappa': kap, 'agree': sum(obs[i][i] for i in range(k)) / n, 'categories': cats, 'weights': weights}


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def describe(values):
    """기술 통계: n, 평균, 표준편차, 가운데값, 최솟값, 최댓값(빈칸·글자는 뺌)."""
    x = sorted(float(v) for v in values if str(v).strip() and _isnum(v))
    if not x:
        raise ValueError('숫자 값이 없습니다.')
    n = len(x)
    med = x[n // 2] if n % 2 else (x[n // 2 - 1] + x[n // 2]) / 2
    return {'test': 'desc', 'n': n, 'm': mean(x), 'sd': sd(x) if n > 1 else 0.0, 'median': med, 'min': x[0], 'max': x[-1],
            'sum': sum(x)}


def freq(values, by=None):
    """빈도와 비율(%). by 를 주면 집단(by 값)마다 따로. 반환: {'test': 'freq', 'groups': {집단: {값: (명, %)}}}."""
    groups = {}
    keys = by if by is not None else [''] * len(values)
    for v, g in zip(values, keys):
        v = str(v).strip()
        if not v:
            continue
        groups.setdefault(str(g).strip(), {}).setdefault(v, 0)
        groups[str(g).strip()][v] += 1
    out = {}
    for g, cnt in groups.items():
        n = sum(cnt.values())
        out[g] = {k: (c, 100.0 * c / n) for k, c in sorted(cnt.items(), key=lambda kv: (not _isnum(kv[0]), _sortkey(kv[0])))}
    return {'test': 'freq', 'groups': out, 'n': sum(sum(c for c, _ in d.values()) for d in out.values())}


def _sortkey(v):
    return float(v) if _isnum(v) else v


def filter_rows(head, rows, where):
    """'열=값' 조건(여러 개는 쉼표)으로 행을 고른다. 예: '경력=초임', '학기=1학기,반=3'."""
    if not where:
        return rows
    conds = []
    for part in where.split(','):
        k, _, v = part.partition('=')
        k = k.strip()
        if k not in head:
            raise ValueError(f'--where 의 열 "{k}" 을 찾지 못했습니다. 있는 열: {", ".join(head)}')
        conds.append((head.index(k), v.strip()))
    return [r for r in rows if all(i < len(r) and r[i].strip() == v for i, v in conds)]


# ------------------------------------------------------------------ 보고서 토큰
def tokens(res, prefix):
    """검정 결과 → 원고에서 쓰는 {{prefix.이름}} 토큰(이미 반올림한 글)."""
    p = prefix + '.' if prefix else ''
    t = {}
    if res.get('test') == 'paired':
        t.update({'n': str(res['n']), 'm0': rd(res['m0']), 's0': rd(res['s0']), 'm1': rd(res['m1']), 's1': rd(res['s1']),
                  'diff': rd(res['diff']), 't': rd(res['t']), 'df': str(res['df']), 'p': fmt_p(res['p']),
                  'dz': rd(res['dz']), 'd': rd(res['dz']), 'dav': rd(res['dav']), 'ci': f"[{rd(res['ci_lo'])}, {rd(res['ci_hi'])}]",
                  'up': str(res['up']), 'same': str(res['same']), 'down': str(res['down']),
                  'upp': rd(100 * res['up'] / res['n'], 1), 'r': nolead(rd(res['r'])), 'eff': effect_label(res['dz'])})
    elif res.get('test') == 'welch':
        t.update({'n0': str(res['n0']), 'n1': str(res['n1']), 'm0': rd(res['m0']), 's0': rd(res['s0']),
                  'm1': rd(res['m1']), 's1': rd(res['s1']), 'diff': rd(res['diff']), 't': rd(res['t']),
                  'df': rd(res['df'], 1), 'p': fmt_p(res['p']), 'g': rd(res['g']), 'd': rd(res['d']),
                  'ci': f"[{rd(res['ci_lo'])}, {rd(res['ci_hi'])}]", 'eff': effect_label(res['g'])})
    elif 'alpha' in res:
        ok = res['alpha'] == res['alpha'] and abs(res['alpha']) != float('inf')
        t.update({'alpha': nolead(rd(res['alpha'])) if ok else '—', 'k': str(res['k']), 'n': str(res['n'])})
    elif 'kappa' in res:
        t.update({'kappa': nolead(rd(res['kappa'])), 'agree': rd(100 * res['agree'], 1), 'n': str(res['n'])})
    elif res.get('test') == 'desc':
        t.update({'n': str(res['n']), 'm': rd(res['m']), 'sd': rd(res['sd']), 'median': _short(res['median']),
                  'min': _short(res['min']), 'max': _short(res['max']), 'sum': _short(res['sum']), 'm1': rd(res['m'], 1)})
    elif res.get('test') == 'freq':
        multi = len(res['groups']) > 1 or '' not in res['groups']
        for g, d in res['groups'].items():
            gp = (g + '.') if multi else ''
            for k, (c, pct) in d.items():
                t[f'{gp}{k}'] = rd(pct, 1)
                t[f'{gp}{k}.n'] = str(c)
            t[f'{gp}n'] = str(sum(c for c, _ in d.values()))
    elif 'r' in res:
        t.update({'r': nolead(rd(res['r'])), 'p': fmt_p(res['p']), 'n': str(res['n']), 'df': str(res['df'])})
    return {p + k: v for k, v in t.items()}


def _short(v):
    """정수면 정수로(4.0 → 4), 아니면 소수 둘째 자리."""
    return str(int(v)) if float(v).is_integer() else rd(v)


def sentence(res):
    """본문에 그대로 쓸 수 있는 한 줄(APA 식)."""
    if res.get('test') == 'paired':
        return (f"M = {rd(res['m0'])}(SD {rd(res['s0'])}) → {rd(res['m1'])}(SD {rd(res['s1'])}), "
                f"t({res['df']}) = {rd(res['t'])}, p {fmt_p(res['p'])}, d = {rd(res['dz'])}, "
                f"변화량 95% CI [{rd(res['ci_lo'])}, {rd(res['ci_hi'])}], n = {res['n']}")
    if res.get('test') == 'welch':
        return (f"M = {rd(res['m0'])}(n = {res['n0']}) → {rd(res['m1'])}(n = {res['n1']}), "
                f"Welch t({rd(res['df'], 1)}) = {rd(res['t'])}, p {fmt_p(res['p'])}, g = {rd(res['g'])}")
    if 'alpha' in res:
        if res['alpha'] != res['alpha']:
            return f"Cronbach's α 를 계산할 수 없음(총점의 분산이 0) ({res['k']}문항, n = {res['n']})"
        return f"Cronbach's α = {nolead(rd(res['alpha']))} ({res['k']}문항, n = {res['n']})"
    if 'kappa' in res:
        return f"가중 κ = {nolead(rd(res['kappa']))}, 완전 일치 {rd(100 * res['agree'], 1)}% (n = {res['n']})"
    if res.get('test') == 'desc':
        return (f"n = {res['n']}, M = {rd(res['m'])}, SD = {rd(res['sd'])}, 가운데값 {_short(res['median'])}, "
                f"범위 {_short(res['min'])}~{_short(res['max'])}")
    if res.get('test') == 'freq':
        parts = []
        for g, d in res['groups'].items():
            n = sum(c for c, _ in d.values())
            body = ', '.join(f'{k} {c}명({rd(p, 1)}%)' for k, (c, p) in d.items())
            parts.append((f'[{g}] ' if g else '') + f'{body} (n = {n})')
        return '\n'.join(parts)
    return f"r = {nolead(rd(res['r']))}, p {fmt_p(res['p'])}, n = {res['n']}"


# ------------------------------------------------------------------ 표 파일 읽기
def read_table(path):
    """CSV(UTF-8/CP949) 또는 XLSX(openpyxl 이 있으면) → (머리글 목록, 행 목록)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm'):
        try:
            import openpyxl
        except ImportError as e:
            raise ValueError('XLSX 를 읽으려면 openpyxl 이 필요합니다(pip install openpyxl). CSV 로 저장해도 됩니다.') from e
        ws = openpyxl.load_workbook(path, data_only=True, read_only=True).active
        rows = [['' if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
        return rows[0], rows[1:]
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949', 'utf-16'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(text.splitlines()))
    rows = [r for r in rows if any(c.strip() for c in r)]
    return [c.strip() for c in rows[0]], rows[1:]


def column(head, rows, name):
    """열 이름(또는 번호) → 값 목록. '사후-사전' 처럼 두 열 이름을 '-' 로 이으면 행마다 차이를 계산한다(변화량)."""
    name = name.strip()
    if name in head:
        i = head.index(name)
    elif name.isdigit() and int(name) < len(head):
        i = int(name)
    else:
        for k in range(1, len(name)):
            if name[k] != '-':
                continue
            a, b = name[:k].strip(), name[k + 1:].strip()
            if a in head and b in head:
                ia, ib = head.index(a), head.index(b)
                out = []
                for r in rows:
                    x = r[ia] if ia < len(r) else ''
                    y = r[ib] if ib < len(r) else ''
                    out.append(_short(float(x) - float(y)) if _isnum(x) and _isnum(y) and str(x).strip() and str(y).strip() else '')
                return out
        raise ValueError(f'열 "{name}" 을 찾지 못했습니다. 있는 열: {", ".join(head)} (두 열의 차이는 "사후열-사전열")')
    return [r[i] if i < len(r) else '' for r in rows]


def _parser():
    import argparse
    ap = argparse.ArgumentParser(prog='hwpx-new stats', description='보고서용 기본 통계(외부 패키지 없이)')
    sub = ap.add_subparsers(dest='kind')
    p = sub.add_parser('paired', help='짝지은 t검정 + d(dz·dav) + 95% CI')
    p.add_argument('file')
    p.add_argument('--pre', required=True)
    p.add_argument('--post', required=True)
    p = sub.add_parser('welch', help='독립 두 집단 Welch t검정 + Hedges g (같은 파일의 두 열, 또는 --group 으로 나눔)')
    p.add_argument('file')
    p.add_argument('--a', required=True, help='첫 집단 열(또는 --group 을 쓸 때 값 열)')
    p.add_argument('--b', help='둘째 집단 열')
    p.add_argument('--group', help='집단 구분 열(값이 두 가지)')
    p = sub.add_parser('alpha', help="Cronbach's α")
    p.add_argument('file')
    p.add_argument('--items', required=True, help='문항 열 이름(쉼표)')
    p = sub.add_parser('kappa', help='가중 카파(평정자 일치도)')
    p.add_argument('file')
    p.add_argument('--r1', required=True)
    p.add_argument('--r2', required=True)
    p.add_argument('--weights', default='linear', choices=['linear', 'quadratic', 'none'])
    p = sub.add_parser('corr', help='Pearson 상관')
    p.add_argument('file')
    p.add_argument('--x', required=True)
    p.add_argument('--y', required=True)
    p = sub.add_parser('desc', help='기술 통계(n, 평균, 표준편차, 가운데값, 범위)')
    p.add_argument('file')
    p.add_argument('--col', required=True)
    p = sub.add_parser('freq', help='빈도·비율(%%) — --by 로 집단마다')
    p.add_argument('file')
    p.add_argument('--col', required=True)
    p.add_argument('--by', help='집단 열(예: 학기)')
    for sp in sub.choices.values():
        sp.add_argument('--prefix', default='', help='원고 토큰 이름 앞부분(예: ref → {{ref.t}})')
        sp.add_argument('--where', help="일부 행만: '열=값'(여러 개는 쉼표). 예: --where 경력=초임")
        sp.add_argument('--json', action='store_true', help='결과를 JSON 으로')
    return ap


def compute(a, base=None):
    """해석된 인자(argparse) → 검정 결과 dict. base: 자료 파일의 상대 경로 기준 폴더."""
    path = a.file if (base is None or os.path.isabs(a.file)) else os.path.join(base, a.file)
    if not os.path.exists(path):
        raise FileNotFoundError(f'자료 파일이 없습니다: {a.file}')
    head, rows = read_table(path)
    rows = filter_rows(head, rows, a.where)
    if not rows:
        raise ValueError(f'조건에 맞는 행이 없습니다: --where {a.where}')
    if a.kind == 'desc':
        return describe(column(head, rows, a.col))
    if a.kind == 'freq':
        return freq(column(head, rows, a.col), column(head, rows, a.by) if a.by else None)
    if a.kind == 'paired':
        return paired(column(head, rows, a.pre), column(head, rows, a.post))
    if a.kind == 'welch':
        if a.group:
            g = column(head, rows, a.group)
            v = column(head, rows, a.a)
            keys = [k for k in dict.fromkeys(x.strip() for x in g) if k]
            if len(keys) != 2:
                raise ValueError(f'집단 열 값이 두 가지여야 합니다: {keys}')
            return welch([x for x, k in zip(v, g) if k.strip() == keys[0]], [x for x, k in zip(v, g) if k.strip() == keys[1]])
        if not a.b:
            raise ValueError('welch 는 --b(둘째 집단 열) 또는 --group(집단 구분 열)이 필요합니다.')
        return welch(column(head, rows, a.a), column(head, rows, a.b))
    if a.kind == 'alpha':
        cols = [column(head, rows, c.strip()) for c in a.items.split(',')]
        return cronbach(list(zip(*cols)))
    if a.kind == 'kappa':
        return kappa(column(head, rows, a.r1), column(head, rows, a.r2), None if a.weights == 'none' else a.weights)
    return pearson(column(head, rows, a.x), column(head, rows, a.y))


def run_line(line, base=None):
    """원고의 '@stats paired 자료.csv --pre 사전 --post 사후 --prefix ref' 한 줄 → (토큰 dict, 한 줄 요약).

    AI 가 숫자를 옮겨 적지 않고 '계산 명령'만 쓰게 하는 장치: 조판할 때마다 자료 파일에서 다시 계산한다."""
    import shlex
    argv = shlex.split(line.replace(chr(92), '/'))          # 윈도 경로의 역슬래시를 / 로(shlex 가 지우지 않게)
    if argv and argv[0] in ('hwpx-new', 'stats'):
        argv = argv[1:] if argv[0] == 'stats' else argv[2:]
    ap = _parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        raise ValueError(f'@stats 줄을 읽지 못했습니다: {line} (예: @stats paired 자료.csv --pre 사전 --post 사후 --prefix ref)')
    if not a.kind:
        raise ValueError(f'@stats 줄에 검정 종류가 없습니다: {line}')
    res = compute(a, base)
    return tokens(res, a.prefix), sentence(res)


def main(argv=None):
    ap = _parser()
    a = ap.parse_args(argv)
    if not a.kind:
        ap.print_help()
        return 0
    res = compute(a)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print(sentence(res))
    tok = tokens(res, a.prefix)
    print()
    print('# 보고서 원고에 붙여 넣을 토큰(본문에서 {{이름}} 으로 사용). 원고에 이 명령을 "@stats …" 한 줄로 쓰면 조판할 때 자동 계산')
    for k, v in tok.items():
        print(f'@set {k} = {v}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
