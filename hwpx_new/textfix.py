# -*- coding: utf-8 -*-
"""한국어 글 다듬기 — 보고서를 조판하기 직전에 자동으로 고치는 것들.

- 번호 뒤 조사: '표 Ⅳ-3과', '그림 2를', '0.62였다' → 받침에 맞게(와/과, 을/를, 은/는, 이/가, 로/으로, 였다/이었다)
- 괄호 뒤 조사: '(교육부, 2024)를' 처럼 괄호 앞 낱말의 받침을 보고 고침(괄호 안 글은 보지 않음)
- 곧은 따옴표 → 굽은 따옴표('…', “…”) — 한글이 든 문단에만(영문 참고문헌의 아포스트로피는 그대로)
- 표·그림·사진 번호 사이 빈칸은 묶음 빈칸(줄 끝에서 '표'와 'Ⅳ-3'이 갈라지지 않게)

AI 가 쓴 글은 조사가 번호·괄호 뒤에서 자주 틀린다(예: '표 3을'). 사람이 하나씩 고치지 않게 조판 단계에서 고친다.
"""
from __future__ import annotations

import re

NBSP = ' '

_JOSA = {'와': ('와', '과'), '과': ('와', '과'), '를': ('를', '을'), '을': ('를', '을'), '는': ('는', '은'),
         '은': ('는', '은'), '가': ('가', '이'), '이': ('가', '이'), '로': ('로', '으로'), '으로': ('로', '으로')}


def _digit_kind(d):
    """숫자 끝소리: V=받침 없음(2·4·5·9), L=ㄹ 받침(1·7·8), C=그 밖의 받침(0·3·6)."""
    return 'V' if d in '2459' else ('L' if d in '178' else 'C')


def fix_ref_josa(text):
    """'표 Ⅳ-3과', '그림 2를', '부록 표 4은' → 번호의 끝소리에 맞는 조사."""
    def rep(m):
        ref, p = m.group(1), m.group(2)
        kind = _digit_kind(re.findall(r'\d+', ref)[-1][-1])
        v, c = _JOSA[p]
        if p in ('로', '으로'):
            return ref + ('로' if kind in 'VL' else '으로')
        return ref + (v if kind == 'V' else c)
    return re.sub(r'((?:부록 표|표|그림|사진)[  ](?:[Ⅰ-Ⅹ]-)?\d+)(으로|와|과|을|를|은|는|이|가|로)(?=[\s,.)」』\'"]|$)',
                  rep, text)


def fix_num_josa(text):
    """'0.62였다', '3명로', '12을' 같은 숫자 바로 뒤 조사."""
    def rep(m):
        d, br, j = m.group(1), m.group(2), m.group(3)
        k = _digit_kind(d)
        if j.startswith(('였', '이었')):
            stem = j[1:] if j.startswith('였') else j[2:]
            return d + br + ('였' if k == 'V' else '이었') + stem
        if j in ('로', '으로'):
            return d + br + ('로' if k in 'VL' else '으로')
        if j in ('와', '과'):
            return d + br + ('와' if k == 'V' else '과')
        if j in ('를', '을'):
            return d + br + ('를' if k == 'V' else '을')
        return m.group(0)
    return re.sub(r'(\d)(\]?)(였다|였으며|였고|였지만|였으나|였는데|이었다|이었으며|이었고|이었지만|이었으나|이었는데|으로|로|와|과|를|을)'
                  r'(?=[\s,.)\]」』\'"·;:]|$)', rep, text)


_PJ = ('이었으며', '이었지만', '이었는데', '이었으나', '이었고', '이었다', '였으며', '였지만', '였는데', '였으나', '였고', '였다',
       '으로', '로', '과', '와', '을', '를', '은', '는', '이', '가')
_PJ_RE = re.compile(r'\)(' + '|'.join(_PJ) + r')(?=[\s,.)\]」』\'"’”·;:]|$)')
_PJ_PAIR = {'과': ('와', '과'), '와': ('와', '과'), '을': ('를', '을'), '를': ('를', '을'),
            '은': ('는', '은'), '는': ('는', '은'), '이': ('가', '이'), '가': ('가', '이')}


def _end_sound(text, b):
    ch = text[b]
    if '가' <= ch <= '힣':
        j = (ord(ch) - 0xAC00) % 28
        return 'V' if j == 0 else ('L' if j == 8 else 'C')
    if ch.isdigit():
        return _digit_kind(ch)
    if ch == '%' or ch in 'κα':
        return 'V'
    if ch.isascii() and ch.isalpha() and not (b and text[b - 1].isascii() and text[b - 1].isalpha()):
        return 'L' if ch in 'LRlr' else ('C' if ch in 'MNmn' else 'V')
    return None


def fix_paren_josa(text):
    """'(교육부, 2024)를' → 괄호 앞 낱말 '교육부'의 받침에 맞춰. 괄호 앞이 한글·숫자가 아니면 고치지 않는다."""
    out, last = [], 0
    for m in _PJ_RE.finditer(text):
        depth, k = 0, m.start()
        while k >= 0:
            if text[k] == ')':
                depth += 1
            elif text[k] == '(':
                depth -= 1
                if depth == 0:
                    break
            k -= 1
        if k <= 0:
            continue
        b = k - 1
        while b > 0 and text[b] in '」』’”\'"':
            b -= 1
        kind = _end_sound(text, b)
        if kind is None:
            continue
        j = m.group(1)
        if j.startswith(('였', '이었')):
            new = ('였' if kind == 'V' else '이었') + (j[1:] if j.startswith('였') else j[2:])
        elif j in ('로', '으로'):
            new = '로' if kind in 'VL' else '으로'
        else:
            v, c = _PJ_PAIR[j]
            new = v if kind == 'V' else c
        out.append(text[last:m.start(1)] + new)
        last = m.end(1)
    out.append(text[last:])
    return ''.join(out)


def smart_quotes(text):
    """한글이 든 글의 곧은 따옴표를 굽은 따옴표로. 영어 낱말 안 아포스트로피(Cohen's)는 그대로."""
    if not re.search('[가-힣]', text):
        return text
    out = []
    for i, ch in enumerate(text):
        prev_c = text[i - 1] if i else ' '
        next_c = text[i + 1] if i + 1 < len(text) else ' '
        if ch == "'" and prev_c.isascii() and prev_c.isalpha() and next_c.isascii() and (next_c.isalpha() or next_c == ' '):
            out.append(ch)
            continue
        if ch in '\'"':
            opening = prev_c.isspace() or prev_c in '([{<—–-/· '
            out.append(('‘' if opening else '’') if ch == "'" else ('“' if opening else '”'))
        else:
            out.append(ch)
    return ''.join(out)


def bind_refs(text):
    """'표 Ⅳ-3', '그림 2', '사진 Ⅴ-1' 의 빈칸을 묶음 빈칸으로(줄 끝에서 갈라지지 않게)."""
    return re.sub(r'(부록 표|표|그림|사진) ((?:[Ⅰ-Ⅹ]-)?\d+)', lambda m: m.group(1) + NBSP + m.group(2), text)


_STAT_EQ = re.compile(r'(?<![가-힣A-Za-z])((?:[A-Za-zκαχη]{1,5}[²w]?)(?:\([^()\s]{1,12}\))?)\s([=<>≤≥])\s(?=[-−]?[.\d])')
_STAT_BARE = re.compile(r'(?<![가-힣A-Za-z])(d|g|r|κw|α)\s(?=[-−]?\.?\d)')
_CI = re.compile(r'\[([-−]?[\d.]+),\s([-−]?[\d.]+)\]')


def bind_stats(text):
    """통계 표현이 줄 끝에서 갈라지지 않게 묶음 빈칸으로: 't(31) = 6.16', 'p < .001', 'κw = .89', 'd 1.09', '[0.44, 0.88]'.

    한글 보고서에서 가장 흔한 조판 실수가 'g =' 다음 줄 '0.33' 처럼 수식이 쪼개지는 것이다."""
    text = _STAT_EQ.sub(lambda m: m.group(1) + NBSP + m.group(2) + NBSP, text)
    text = _STAT_BARE.sub(lambda m: m.group(1) + NBSP, text)
    return _CI.sub(lambda m: f'[{m.group(1)},{NBSP}{m.group(2)}]', text)


def polish(text):
    """보고서 문단 하나를 다듬는다(조사·따옴표·통계 표현 묶기). 표·그림 번호 묶음 빈칸은 참조를 풀 때 넣는다."""
    return bind_stats(smart_quotes(fix_paren_josa(fix_num_josa(fix_ref_josa(text)))))
