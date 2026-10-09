# -*- coding: utf-8 -*-
"""정돈 조판(compose)과 이번에 고친 엔진 동작 회귀 테스트(한글 없이 XML 구조로 확인)."""
import json
import os
import sys
import tempfile
import zipfile

from lxml import etree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TPL = os.path.join(ROOT, 'examples', 'sample_template.hwpx')
HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'


def _read(path):
    z = zipfile.ZipFile(path)
    return etree.fromstring(z.read('Contents/header.xml')), etree.fromstring(z.read('Contents/section0.xml'))


def _text(p):
    return ''.join(''.join(t.itertext()) for r in p.findall(HP + 'run') for t in r.findall(HP + 't'))


def test_compose_structure():
    from hwpx_new.compose import Composer
    from hwpx_new.validate import validate
    d = Composer(TPL)
    d.section_start()
    d.h1('Ⅰ', '추진 개요')
    d.h2('목적')
    d.b1('긴 항목 문장입니다. ' * 6)
    d.b2('세부 항목')
    d.note('참고 ^^마감^^', level=1)
    d.table([9000, 39000], [['구분', '내용'], ['기간', '2026. 11. 21.(토)\n- 변경 가능']], label_col=True, aligns=['c', 'l'])
    d.table([5000, 43000], [['번호', '이름']] + [[str(i), ''] for i in range(30)], split=True)
    d.box([('bx1', '❍ 박스 항목')], title='안내')
    out = os.path.join(tempfile.mkdtemp(), 'c.hwpx')
    d.save(out, title='시험')
    head, sec = _read(out)
    assert head.get('secCnt') == '1'
    errs = validate(out)
    assert not [e for e in errs if '참조' in e], errs
    texts = [_text(p) for p in sec.iter(HP + 'p')]
    assert any(t.startswith('■') and '목적' in t for t in texts)
    assert any(t.startswith('❍') for t in texts)
    # 줄머리 기호 뒤는 묶음 빈칸(양쪽 정렬에서 내어쓰기와 정확히 맞도록)
    assert sec.find('.//' + HP + 'nbSpace') is not None
    # 강조색은 지정한 한 가지(진한 빨강)만 새로 쓰인다
    colors = {c.get('textColor') for c in head.iter(HH + 'charPr')}
    assert '#C00000' in colors
    # 긴 표(split)는 떠 있는 표(행 단위로 쪽 나눔), 짧은 표는 글자처럼 취급
    tbls = list(sec.iter(HP + 'tbl'))
    flags = [(t.get('rowCnt'), t.find(HP + 'pos').get('treatAsChar'), t.get('pageBreak')) for t in tbls]
    assert ('31', '0', 'TABLE') in flags
    assert ('2', '1', 'NONE') in flags
    # 표 칸 머리 행에는 묶음 빈칸을 쓰지 않는다(좁은 칸에서 글자 중간 줄바꿈 방지)
    first = tbls[0].find('.//' + HP + 'tc')
    assert first.find('.//' + HP + 'nbSpace') is None


def test_word_wrap_semantics():
    """제목·표 칸 = 어절 단위(BREAK_WORD), 본문 = 글자 단위(KEEP_WORD) — 한글 실측 의미."""
    from hwpx_new.compose import Composer
    d = Composer(TPL)
    pid_h2 = d.style_ids('h2')[0]
    pid_b1 = d.style_ids('b1')[0]
    box = d._box('paraProperties')
    by = {p.get('id'): p for p in box.findall(HH + 'paraPr')}
    assert by[pid_h2].find(HH + 'breakSetting').get('breakNonLatinWord') == 'BREAK_WORD'
    assert by[pid_b1].find(HH + 'breakSetting').get('breakNonLatinWord') == 'KEEP_WORD'


def test_clone_paras_like_insert():
    """clone paras 에 {"like":k} 로 문단을 끼워 넣고, 남는 원래 문단은 지운다."""
    from hwpx_new.analyze import analyze
    from hwpx_new.pipeline import build_once
    bp = analyze(TPL)
    # 글이 있는 문단이 2개 이상인 표 블록을 찾는다
    target = None
    for b in bp.blocks:
        if b.el.find('.//' + HP + 'tbl') is None:
            continue
        slots = [p for p in b.el.iter(HP + 'p') if p is not b.el and _text(p).strip()]
        if len(slots) >= 3:
            target = (b.idx, len(slots))
            break
    assert target, '시험용 표 블록 없음'
    idx, n = target
    specs = [{'type': 'clone', 'from': idx, 'paras': ['첫 문단', {'like': 0, 'text': '끼워 넣은 문단'}, '둘째 문단']}]
    out = os.path.join(tempfile.mkdtemp(), 'p.hwpx')
    build_once(TPL, specs, [], 0, out, '시험')
    _, sec = _read(out)
    texts = [_text(p) for p in sec.iter(HP + 'p') if _text(p).strip()]
    assert '끼워 넣은 문단' in texts
    i0, i1, i2 = texts.index('첫 문단'), texts.index('끼워 넣은 문단'), texts.index('둘째 문단')
    assert i0 < i1 < i2
    assert len([t for t in texts]) <= n + 3


if __name__ == '__main__':
    test_compose_structure()
    test_word_wrap_semantics()
    test_clone_paras_like_insert()
    print('compose OK')
