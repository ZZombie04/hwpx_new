# -*- coding: utf-8 -*-
"""보고서 점검(report check) — 사람 심사자가 가장 먼저 짚는 실수를 기계로 먼저 찾는다.

오류(반드시 고침)
- 풀지 못한 {{토큰}}·{표:키} 참조, 원고에 없는 사진·그림 파일
- 본문 인용(저자, 연도)이 참고문헌에 없음
- 날짜와 요일이 맞지 않음(예: 2026. 11. 5.(수) → 목요일)
- 본문 쪽수가 상한(page_limit)을 넘음
주의(되도록 고침)
- 참고문헌에 있지만 본문에서 인용하지 않은 문헌
- 본문에서 한 번도 가리키지 않은 표·그림·사진
- 근거보다 큰 말(입증·획기적·완벽 …), 검정 결과(p) 없이 '유의'라고 쓴 문장
- 장 끝이 아닌데 아래쪽이 35% 넘게 빈 쪽
정보: 국외 문헌 비율, 쪽 구성
"""
from __future__ import annotations

import datetime as _dt
import re

OVERCLAIM = ['입증', '증명하였', '증명되었', '획기적', '완벽하게', '완벽한 효과', '확실히 효과', '반드시 효과', '절대적']
WEEK = '월화수목금토일'


def _texts(ms):
    """원고의 본문 글(참고문헌 줄 제외)을 (위치, 글) 로 모은다."""
    out = []
    for part, blocks in (('앞부분', ms.front), ('본문', ms.body), ('부록', ms.appx)):
        for b in blocks:
            k = b[0]
            if k in ('p', 'k'):
                out.append((part, b[1]))
            elif k == 'table':
                for r in b[2]:
                    for c in r:
                        out.append((part + '·표', c['t'] if isinstance(c, dict) else c))
                out.append((part, ' '.join(b[1][1:2])))
            elif k in ('box', 'voice', 'kpi'):
                out.extend((part, x) for x in b[2])
                if b[1]:
                    out.append((part, b[1][0]))
            elif k in ('tnote', 'sec', 'sub', 'ssub', 'ch', 'fsub', 'ftitle', 'appx'):
                out.append((part, ' '.join(b[1])))
            elif k in ('fig', 'chart', 'photos'):
                out.append((part, ' '.join(b[1][1:])))
    return out


def _refs(ms):
    return [b[1][0] if len(b[1]) == 1 else ' | '.join(b[1]) for b in ms.body + ms.appx if b[0] == 'r']


_INITIAL = re.compile(r'^(?=.*\.)([A-Z]\.?\s*)+$')      # 'T. R.'·'T. R'(끝 마침표가 잘린 경우) — 'KEDI' 같은 약칭은 제외


def _authors(s):
    """'서정화, 송영식' / 'Guskey, T. R.' / '한국직업능력연구원 편' / '정주영, 안영식, 홍광표' → 이름 목록."""
    s = s.replace('&', ',').replace(' and ', ',').replace('·', ',')
    names = []
    for part in [x.strip() for x in s.split(',')]:
        if not part:
            continue
        part = re.sub(r'\s*(편|엮음|외|et al\.?)$', '', part).strip()
        if _INITIAL.match(part) or len(part) <= 1:
            continue
        names.append(part.split()[-1] if re.match(r'^[A-Za-z]', part) and ' ' in part and not part.isupper() else part)
    return names


def parse_reference(line):
    """참고문헌 한 줄 → {'authors': [...], 'year': '2024a', 'law': '「…」', 'foreign': bool}."""
    t = line.strip()
    law = re.match(r'^(「[^」]+」)', t)
    if law:
        return {'authors': [], 'year': None, 'law': law.group(1), 'foreign': False, 'text': t}
    m = re.match(r'^(.*?)\s*\((\d{4}[a-z]?)[^)]*\)', t)
    if not m:
        return {'authors': [], 'year': None, 'law': None, 'foreign': bool(re.match(r'^[A-Za-z]', t)), 'text': t}
    au = m.group(1).strip().rstrip('.,')
    return {'authors': _authors(au), 'year': m.group(2), 'law': None, 'foreign': bool(re.match(r'^[A-Za-z]', au)), 'text': t}


_YEAR = r'(\d{4}[a-z]?)'


def citations(text):
    """본문 글 → [(저자 첫 이름, 연도, 원문)]."""
    out = []
    for m in re.finditer(r'\(([^()]*?\d{4}[a-z]?[^()]*?)\)', text):
        inner = m.group(1)
        for part in inner.split(';'):
            part = part.strip()
            mm = re.match(r'^(.*?)[,\s]\s*' + _YEAR + r'(?:[,:]\s*(?:p+\.\s*)?[\d\-–]+)?$', part)
            if not mm:
                continue
            au = mm.group(1).strip().rstrip(',')
            if not au or re.search(r'\d', au) or not re.search(r'[가-힣A-Za-z]', au) or len(au) > 40:
                continue
            if re.search(r'(기준|부터|까지|학년도|년|월|일|쪽|명|회|건|시행|개정|공포)$', au):
                continue
            names = _authors(au)
            if names:
                out.append((names[0], mm.group(2), part, 'paren'))
    for m in re.finditer(r'([가-힣]{2,12}|[A-Z][A-Za-z\-]+)\s?\(' + _YEAR + r'\)', text):
        name = m.group(1)
        if name in ('표', '그림', '사진', '부록', '연도', '기준'):
            continue
        out.append((name, m.group(2), m.group(0), 'narr'))
    return out


def _weekday_issues(text, year):
    out = []
    for m in re.finditer(r'(?:(\d{4})\.\s?)?(\d{1,2})\.\s?(\d{1,2})\.\s?\(([월화수목금토일])\)', text):
        y = int(m.group(1)) if m.group(1) else year
        if not y:
            continue
        try:
            d = _dt.date(y, int(m.group(2)), int(m.group(3)))
        except ValueError:
            out.append(f'없는 날짜: {m.group(0)}')
            continue
        real = WEEK[d.weekday()]
        if real != m.group(4):
            out.append(f'요일이 맞지 않음: {m.group(0)} → {y}년 {d.month}월 {d.day}일은 {real}요일')
    return out


def check(ms, pdf=None, builder=None, page_limit=None, year=None):
    """반환: [(수준, 메시지)] — 수준은 '오류' | '주의' | '정보'."""
    from .report import Builder
    cfg = ms.config
    issues = []
    B = builder or Builder(ms)
    texts = _texts(ms)
    if builder is None:
        for _, t in texts:
            B.sub(t)
    for m in sorted(B.missing):
        if m.startswith('pages.'):
            continue
        issues.append(('오류', f'풀지 못한 토큰·참조: {m} ({{{{이름}}}} 은 @set 이나 facts 에, {{표:키}} 는 같은 키의 @table 이 있어야 함)'))
    whole = '\n'.join(t for _, t in texts)
    raw = '\n'.join(open(p, encoding='utf-8-sig').read() for p in ms.sources)
    for rk, lab in B.refs.items():
        kind, key = rk.split(':', 1)
        if lab.startswith('부록') or kind == '사진':
            continue
        if not re.search(r'\{(' + kind + r'):\s*' + re.escape(key) + r'\s*\}', raw):
            issues.append(('주의', f'본문에서 가리키지 않은 {lab}(키 {key}) — 본문에 {{{kind}:{key}}} 로 한 번 이상 언급'))
    # 인용 ↔ 참고문헌
    refs = [parse_reference(r) for r in _refs(ms)]
    if refs:
        index = {}
        for i, r in enumerate(refs):
            for a in r['authors']:
                index.setdefault((a, r['year']), set()).add(i)
        used = set()
        seen = set()
        for name, yr, src, how in citations(whole):
            hit = index.get((name, yr))
            if hit:
                used |= hit
                continue
            if (name, yr) in seen:
                continue
            seen.add((name, yr))
            cands = [i for (a, y), ids in index.items() if a == name for i in ids]
            if cands:
                issues.append(('오류', f'인용 연도가 참고문헌과 다름: "{src}" (참고문헌: {", ".join(refs[i]["text"][:30] for i in cands)})'))
            elif how == 'paren':
                issues.append(('오류', f'참고문헌에 없는 인용: "{src}"'))
            else:
                issues.append(('주의', f'참고문헌에 없는 인용으로 보임: "{src}" (인용이 아니라 사례·기관 이름이면 무시)'))
        for i, r in enumerate(refs):
            if r['law']:
                if r['law'] in whole:
                    used.add(i)
                continue
            if i not in used and r['authors']:
                issues.append(('주의', f'본문에서 인용하지 않은 참고문헌: {r["text"][:60]}'))
        nf = sum(1 for r in refs if r['foreign'])
        issues.append(('정보', f'참고문헌 {len(refs)}편(국외 {nf}편, {round(100 * nf / len(refs))}%)'))
    # 근거보다 큰 말, 검정 없는 '유의'
    for part, t in texts:
        for w in OVERCLAIM:
            if w in t:
                i = t.index(w)
                issues.append(('주의', f'근거보다 큰 말 "{w}": …{t[max(0, i - 20):i + 20]}…'))
        if (not part.endswith('·표') and re.search(r'유의(하게|한|미한)', t)
                and not re.search(r'\bp\s?[<=>]|p\s?\{\{|\{\{[^}]*\.p\}\}|유의수준|유의도|\br\s?=|\bt\(|\bF\(|χ|검정', t)):
            issues.append(('주의', f'검정 결과(p) 없이 "유의": …{t[:50]}…'))
    # 날짜·요일
    yr = year or cfg.get('year')
    if not yr:
        m = re.search(r'(20\d{2})', str(cfg.get('date', '')) + ' ' + str(cfg.get('title', '')))
        yr = int(m.group(1)) if m else None
    for _, t in texts:
        for msg in _weekday_issues(B.sub(t, polish=False) if '{{' in t else t, int(yr) if yr else None):
            issues.append(('오류', msg))
    # 쪽
    if pdf:
        from .report import map_pages, page_gaps, read_pdf
        try:
            _, info = map_pages(B, pdf)
            lim = page_limit or cfg.get('page_limit')
            issues.append(('정보', f"쪽: 전체 {info['total']} = 앞부분 {info['front']} + 본문 {info['body']} + 참고문헌 {info['refs']} + 부록 {info['appx']}"))
            if lim and info['body'] + info['refs'] > int(lim):
                issues.append(('오류', f"본문+참고문헌 {info['body'] + info['refs']}쪽이 상한 {lim}쪽을 넘습니다."))
            labels, ptexts = read_pdf(pdf)
            ch_titles = [_n(f'{b[1][0]}{b[1][1]}') for b in ms.body if b[0] == 'ch'] + ['참고문헌', '부록']
            gaps = page_gaps(pdf)
            for g in gaps:
                i = g['index'] - 1
                if not g['label'] or i + 1 >= len(ptexts) or g['gap'] < 0.35:
                    continue
                nxt = ptexts[i + 1]
                if any(t and nxt.startswith(t[:10]) or (t and t[:12] in nxt[:80]) for t in ch_titles):
                    continue
                issues.append(('주의', f"{g['label']}쪽 아래가 {round(g['gap'] * 100)}% 비어 있음(큰 표·그림·사진이 다음 쪽으로 밀림 → 순서를 바꾸거나 글을 보강)"))
        except Exception as e:  # noqa
            issues.append(('주의', f'PDF 쪽 점검을 하지 못함: {e}'))
    for line, err in getattr(ms, 'stat_errors', []):
        issues.append(('오류', f'@stats 계산 실패: {line} → {err}'))
    for line, summary, toks in getattr(ms, 'stat_log', []):
        if line.split()[:1] == ['alpha']:
            v = next((ms.facts.get(t) for t in toks if t.endswith('alpha')), None)
            if v in ('—', 'NaN', 'nan'):
                issues.append(('주의', f'신뢰도를 계산할 수 없음(문항 점수의 분산이 0): {line} — 자료를 확인하세요'))
                continue
            try:
                a = float(v)
            except (TypeError, ValueError):
                continue
            if a < .60:
                issues.append(('주의', f'신뢰도가 낮음(α = {v}): {line} — 역문항·문항 내용을 확인하고, 그대로 쓰면 한계에 밝힌다(.70 이상 권장)'))
    for w in getattr(ms, 'warnings', []):
        issues.append(('주의', w))
    for w in sorted(getattr(B, 'warn', ())):
        issues.append(('주의', w))
    order = {'오류': 0, '주의': 1, '정보': 2}
    return sorted(issues, key=lambda x: order[x[0]])


def _n(s):
    return re.sub(r'\s+', '', s)


def main(argv=None):
    import argparse
    from .report import read_manuscript
    ap = argparse.ArgumentParser(prog='hwpx-new report check')
    ap.add_argument('manuscript')
    ap.add_argument('--pdf')
    ap.add_argument('--page-limit', type=int)
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args(argv)
    ms = read_manuscript(a.manuscript)
    iss = check(ms, a.pdf, page_limit=a.page_limit)
    errs = sum(1 for x in iss if x[0] == '오류')
    for lv, msg in iss:
        print(f'[{lv}] {msg}')
    print(f'결과: 오류 {errs}, 주의 {sum(1 for x in iss if x[0] == "주의")}')
    return 1 if (a.strict and errs) else 0
