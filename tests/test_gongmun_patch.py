# -*- coding: utf-8 -*-
"""공문 명세(gongmun)·조판 명세(compose spec)·고치기(patch/replace) 시험 — 한글 없이 HWPX 구조만 확인."""
import os
import sys
import tempfile
import zipfile

import pytest
from lxml import etree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hwpx_new.compose import Composer, HP  # noqa: E402
from hwpx_new import gongmun, spec, patch  # noqa: E402

TPL = os.path.join(ROOT, 'hwpx_new', 'data', 'sample_template.hwpx')


def _t(t):
    """t 요소의 글(묶음 빈칸은 빈칸으로)."""
    s = t.text or ''
    for ch in t:
        s += (' ' if ch.tag.endswith(('nbSpace', 'fwSpace')) else '') + (ch.tail or '')
    return s


def paras(path):
    z = zipfile.ZipFile(path)
    out = []
    for p in etree.fromstring(z.read('Contents/section0.xml')).iter(HP + 'p'):
        t = ''.join(_t(x) for r in p.findall(HP + 'run') for x in r.findall(HP + 't')).strip()
        if t:
            out.append(t)
    return out


@pytest.fixture(scope='module')
def tmp():
    return tempfile.mkdtemp(prefix='hwpx_gm_')


@pytest.fixture(scope='module')
def gm_template(tmp):
    """머리 표(수신·제목) + 본문 한 줄 + 결재란(시행·협조자)만 있는 공문 서식."""
    d = Composer(TPL)
    d.section_start()
    d.table([12000, 36190], [['기관명', '○○교육지원청'], ['수신', '내부결재'], ['(경유)', ''], ['제목', '옛 제목']], head=0)
    d.p('1. 서식 본문 예시', 'p')
    d.table([8000, 16000, 8000, 16190], [['시행', '옛번호', '접수', ''], ['협조자', '', '', '']], head=0)
    out = os.path.join(tmp, 'gm_tpl.hwpx')
    d.save(out, title='공문 서식')
    return out


def test_gongmun_build(tmp, gm_template):
    out = os.path.join(tmp, 'gm.hwpx')
    gongmun.build({
        'template': gm_template, 'receiver': '수신자 참조', 'title': '대회 참가 신청 안내',
        'body': ['1. 관련: 예시 계획', '2. 대회를 다음과 같이 운영합니다.', '가. 대회 개요',
                 {'table': {'label_col': True, 'rows': [['일시', '2026. 11. 21.(토)'], ['장소', '체육관']]}},
                 '※ 일정은 바뀔 수 있습니다.', '3. 문의: 예시과'],
        'attachments': ['대회 운영 계획'], 'sender': '○○교육지원청교육장', 'receivers': ['가초등학교장', '나초등학교장'],
        'approval': {'시행': '예시과-1234(2026. 10. 9.)'}}, out)
    ps = paras(out)
    assert '수신자 참조' in ps and '대회 참가 신청 안내' in ps and '내부결재' not in ps and '옛 제목' not in ps
    assert ps.index('1. 관련: 예시 계획') < ps.index('일시') < ps.index('※ 일정은 바뀔 수 있습니다.')
    assert '붙임  대회 운영 계획 1부.  끝.' in ps
    assert ps.index('○○교육지원청교육장') < ps.index('수신자  가초등학교장, 나초등학교장') < ps.index('예시과-1234(2026. 10. 9.)')
    assert '1. 서식 본문 예시' not in ps        # 서식 본문은 버리고 머리 표·결재란만 복제


def test_gongmun_end_mark_without_attachment(tmp, gm_template):
    out = os.path.join(tmp, 'gm2.hwpx')
    gongmun.build({'template': gm_template, 'receiver': '내부결재', 'title': '계획 수립',
                   'body': ['1. 관련: 예시', '2. 붙임과 같이 수립하고자 합니다.']}, out)
    assert '2. 붙임과 같이 수립하고자 합니다.  끝.' in paras(out)


def test_gongmun_needs_cover(tmp):
    with pytest.raises(ValueError):
        gongmun.build({'template': TPL, 'title': 'x', 'body': []}, os.path.join(tmp, 'bad.hwpx'))


def test_compose_spec_and_patch(tmp):
    src = os.path.join(tmp, 'plan.hwpx')
    spec.build({'template': TPL, 'title': '계획', 'blocks': [
        {'h1': 'Ⅰ 추진 개요'}, {'h2': '목적'}, {'b1': '표창 계획 없음'}, {'b1': '참가비 없음'},
        {'h2': '운영 원칙'}, {'b1': '원칙 하나'},
        {'table': {'label_col': True, 'rows': [['기간', '11월'], ['장소', '체육관']]}},
        {'h1': 'Ⅱ 행정 사항'}, {'b1': '문의'}]}, src)
    ps = paras(src)
    assert ps[:3] == ['Ⅰ', '추진 개요', '■ 목적'] or '■ 목적' in ps
    out = os.path.join(tmp, 'plan_patched.hwpx')
    rep = patch.patch(src, [
        {'op': 'replace_text', 'find': '참가비 없음', 'to': '참가비 1만원'},
        {'op': 'replace_block', 'find': '표창 계획 없음', 'blocks': [{'b1': '1위 팀 지도교사 표창'}]},
        {'op': 'insert_after', 'find': '■ 운영 원칙', 'blocks': [{'b1': '새 원칙'}]},
        {'op': 'page_break', 'find': 'Ⅱ 행정 사항', 'on': True}], out)
    ps = paras(out)
    assert any('참가비 1만원' in t for t in ps) and not any('표창 계획 없음' in t for t in ps)
    assert [t for t in ps if '새 원칙' in t or '원칙 하나' in t][0].endswith('새 원칙')
    assert len(rep) == 4
    with pytest.raises(ValueError):          # 찾는 글이 여러 블록에 있으면 멈춘다
        patch.patch(src, [{'op': 'delete_block', 'find': '원칙'}], os.path.join(tmp, 'x.hwpx'))
    with pytest.raises(ValueError):          # 바꿀 글이 없으면 멈춘다
        patch.patch(src, [{'op': 'replace_text', 'find': '없는 글', 'to': 'y'}], os.path.join(tmp, 'y.hwpx'))


def test_replace_text_zip_preserves_other_entries(tmp):
    src = os.path.join(tmp, 'plan.hwpx')
    if not os.path.exists(src):
        spec.build({'template': TPL, 'blocks': [{'b1': '2026 평가 축제'}]}, src)
    out = os.path.join(tmp, 'renamed.hwpx')
    hits = patch.replace_text_zip(src, out, [('추진 개요', '운영 개요')])
    assert hits['추진 개요'] >= 1
    a, b = zipfile.ZipFile(src), zipfile.ZipFile(out)
    assert a.namelist() == b.namelist()
    for n in a.namelist():
        if not n.startswith(patch.TEXT_ENTRIES):
            assert a.read(n) == b.read(n), n
    assert any('운영 개요' in t for t in paras(out))
    assert patch.saved_by_hancom(out) is False
