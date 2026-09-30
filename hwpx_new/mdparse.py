# -*- coding: utf-8 -*-
"""Markdown(확장) → 블록 목록. AI 가 가장 안정적으로 쓸 수 있는 입력 형식."""
from __future__ import annotations

import json
import re

IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
TAG_RE = re.compile(r'^\{([A-Z]\d{1,3})\}\s*')
NUM_RE = re.compile(r'^(\d{1,2}\s*[\.\)]|[가-힣]\s*[\.\)]|\(\d{1,2}\)|[①-⑳])\s*\S')


def _split_row(line: str):
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|') and not line.endswith('\\|'):
        line = line[:-1]
    cells = re.split(r'(?<!\\)\|', line)
    return [c.strip().replace('\\|', '|').replace('<br>', '\n').replace('<br/>', '\n') for c in cells]


def _is_sep(line: str):
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r':?-{1,}:?', c) for c in cells if c != '') and any(cells)


def parse_markdown(text: str):
    lines = text.replace('\r\n', '\n').split('\n')
    blocks = []
    pending = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        i += 1
        if not s:
            continue
        m = re.fullmatch(r'<!--\s*(pagebreak|page_break|쪽나눔)\s*-->|-{3,}\s*pagebreak\s*-{3,}', s, re.I)
        if m:
            pending['page_break'] = True
            continue
        m = re.fullmatch(r'<!--\s*class\s*:\s*([A-Z]\d{1,3})\s*-->', s)
        if m:
            pending['class'] = m.group(1)
            continue
        m = re.fullmatch(r'<!--\s*(widths|min_row)\s*:\s*([^>]*?)\s*-->', s)
        if m:
            if m.group(1) == 'widths':
                pending['widths'] = [float(x) for x in re.split(r'[,\s]+', m.group(2).strip()) if x]
            else:
                pending['min_row'] = int(m.group(2))
            continue
        if s.startswith('<!--'):
            continue
        def emit(b):
            if pending.pop('page_break', False):
                b['page_break'] = True
            if 'class' in pending and b.get('type') == 'table':
                b['class'] = pending.pop('class')
            blocks.append(b)

        def tagged(text):
            m_ = TAG_RE.match(text)
            if m_:
                return text[m_.end():], m_.group(1)
            return text, None

        if s.startswith('```'):
            lang = s[3:].strip().lower()
            body = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                body.append(lines[i])
                i += 1
            i += 1
            if lang in ('json', ''):
                try:
                    data = json.loads('\n'.join(body))
                except ValueError as e:
                    raise ValueError(f'```json 블록({i - len(body)}번째 줄 근처)을 읽을 수 없습니다: {e}. '
                                     '따옴표·쉼표·괄호를 확인하거나, 블록 구조는 그대로 두고 글만 바꾸세요.')
                for d in (data if isinstance(data, list) else [data]):
                    emit(d)
            continue
        m = re.match(r'^@like\s+(\d+)\s*\|\s?(.*)$', raw.strip())
        if m:
            emit({'type': 'like', 'from': int(m.group(1)), 'text': m.group(2)})
            continue
        m = re.match(r'^@clone\s+(?:(\d+):)?(\d+)(?:\s*[-~]\s*(\d+))?\s*$', s)
        if m:
            d = {'type': 'clone', 'from': int(m.group(2))}
            if m.group(3):
                d['to'] = int(m.group(3))
            if m.group(1):
                d['section'] = int(m.group(1))
            emit(d)
            continue
        if s.startswith(':::cover'):
            fields = []
            while i < len(lines) and lines[i].strip() != ':::':
                fields.append(lines[i].strip())
                i += 1
            i += 1
            fields = [f for f in fields if f != ''] if not any(f == '' for f in fields[:0]) else fields
            emit({'type': 'title', 'text': max(fields, key=len) if fields else '', 'fields': fields})
            continue

        if s.startswith(':::box'):
            title, box_cls = tagged(s[len(':::box'):].strip())
            title = title or None
            body = []
            while i < len(lines) and lines[i].strip() != ':::':
                if lines[i].strip():
                    body.append(lines[i].strip())
                i += 1
            i += 1
            if title is None and body:
                title, body = body[0], body[1:]
            bx = {'type': 'box', 'title': title, 'lines': body}
            if box_cls:
                bx['class'] = box_cls
            emit(bx)
            continue
        if s.startswith(':::photos'):
            opts = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', s[len(':::photos'):]))
            opts = {k: v.strip('"') for k, v in opts.items()}
            imgs = []
            while i < len(lines) and lines[i].strip() != ':::':
                for cap, path in IMG_RE.findall(lines[i]):
                    imgs.append({'path': path.strip(), 'caption': cap.strip()})
                i += 1
            i += 1
            g = {'type': 'gallery', 'images': imgs}
            if 'columns' in opts:
                g['columns'] = int(opts['columns'])
            if 'title' in opts:
                g['title'] = opts['title']
            if 'width_mm' in opts:
                g['width_mm'] = float(opts['width_mm'])
            if 'max_height_mm' in opts:
                g['max_height_mm'] = float(opts['max_height_mm'])
            emit(g)
            continue
        found = IMG_RE.findall(s)
        if found and IMG_RE.sub('', s).strip() == '':
            if len(found) == 1:
                emit({'type': 'image', 'path': found[0][1].strip(), 'caption': found[0][0].strip()})
            else:
                emit({'type': 'gallery', 'columns': min(len(found), 4),
                      'images': [{'path': pth.strip(), 'caption': cap.strip()} for cap, pth in found]})
            continue
        if s.startswith('|'):
            tbl = [s]
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl.append(lines[i].strip())
                i += 1
            seps = [k for k, l in enumerate(tbl) if _is_sep(l)]
            aligns = None
            if seps:
                k = seps[0]
                head = [_split_row(l) for l in tbl[:k]]
                aligns = []
                for c in _split_row(tbl[k]):
                    if c.startswith(':') and c.endswith(':'):
                        aligns.append('c')
                    elif c.endswith(':'):
                        aligns.append('r')
                    elif c.startswith(':'):
                        aligns.append('l')
                    else:
                        aligns.append(None)
                body = [_split_row(l) for l in tbl[k + 1:] if not _is_sep(l)]
            else:
                head, body = [_split_row(tbl[0])], [_split_row(l) for l in tbl[1:]]
            b = {'type': 'table', 'header': head[0] if len(head) == 1 else head, 'rows': body}
            if aligns and any(aligns):
                b['align'] = [a for a in aligns]
            for key in ('widths', 'min_row'):
                if key in pending:
                    b[key] = pending.pop(key)
            emit(b)
            continue
        if s.startswith('@subtitle'):
            emit({'type': 'subtitle', 'text': s[len('@subtitle'):].strip()})
            continue
        if s.startswith('@end'):
            emit({'type': 'end', 'text': s[len('@end'):].strip() or '끝.'})
            continue
        if s.startswith('@blank'):
            blocks.append({'type': 'blank'})
            continue
        if s.startswith('# '):
            emit({'type': 'title', 'text': s[2:].strip()})
            continue
        if s.startswith('## '):
            t_, c_ = tagged(s[3:].strip())
            d = {'type': 'heading', 'text': t_}
            if c_:
                d['class'] = c_
            emit(d)
            continue
        m = re.match(r'^(\s*)([-*•])\s+(.*)$', raw)
        if m:
            indent = len(m.group(1).replace('\t', '  '))
            t_, c_ = tagged(m.group(3).strip())
            d = {'type': 'bullet', 'text': t_, 'level': indent // 2 + 1}
            if c_:
                d['class'] = c_
            emit(d)
            continue
        t_, c_ = tagged(s)
        if t_.startswith('### ') or NUM_RE.match(t_):
            d = {'type': 'numbered', 'text': t_[4:].strip() if t_.startswith('### ') else t_}
        else:
            d = {'type': 'paragraph', 'text': t_}
        if c_:
            d['class'] = c_
        emit(d)
    return blocks


def _unwrap_fence(text: str) -> str:
    """AI 가 전체 Markdown 을 ```markdown … ``` 으로 감싸 보낸 경우 바깥 울타리를 벗긴다(안쪽 ```json 은 그대로)."""
    lines = text.strip().split(chr(10))
    if len(lines) >= 2 and re.match(r'^```\s*(markdown|md)?\s*$', lines[0].strip(), re.I) and lines[-1].strip() == '```':
        return chr(10).join(lines[1:-1])
    return text


def load_content(src: str):
    """파일 경로 / JSON 문자열 / Markdown 문자열 → (블록 목록, 메타)"""
    import os
    text = src
    if len(src) < 500 and os.path.exists(src):
        text = open(src, encoding='utf-8').read()
    t = text.lstrip()
    meta = {}
    if t.startswith('{') or t.startswith('['):
        data = json.loads(t)
        if isinstance(data, dict):
            meta = {k: v for k, v in data.items() if k != 'blocks'}
            return data.get('blocks', []), meta
        return data, meta
    return parse_markdown(_unwrap_fence(text)), meta
