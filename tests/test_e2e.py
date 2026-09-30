# -*- coding: utf-8 -*-
"""종단 테스트: 서식 분석 → 조립 → PDF → 조판 점검 (내장 렌더러 사용, 한글 없이도 통과)."""
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hwpx_new.analyze import analyze, scaffold_markdown  # noqa: E402
from hwpx_new.mdparse import parse_markdown  # noqa: E402
from hwpx_new.pipeline import lint_content, make_report  # noqa: E402

TPL = os.path.join(ROOT, 'examples', 'sample_template.hwpx')
MD = os.path.join(ROOT, 'examples', 'sample_content.md')


def test_analyze_roles():
    bp = analyze(TPL)
    roles = {}
    for b in bp.blocks:
        roles[b.role] = roles.get(b.role, 0) + 1
    assert roles['title'] == 1 and roles['heading'] == 5 and roles['table'] == 3 and roles['box'] == 1
    assert roles.get('subtitle') == 1 and roles['bullet'] >= 5
    assert 'Ⅰ.' in scaffold_markdown(bp)


def test_markdown_parse():
    blocks = parse_markdown(open(MD, encoding='utf-8').read())
    types = [b['type'] for b in blocks]
    assert types[0] == 'title' and 'box' in types and types.count('table') == 5 and types[-1] == 'end'
    lv = [b['level'] for b in blocks if b['type'] == 'bullet']
    assert 2 in lv


def test_lint_weekday():
    w = lint_content([{'type': 'paragraph', 'text': '2026. 9. 16.(화)에 실시'}])
    assert w and '요일 불일치' in w[0]
    assert not lint_content([{'type': 'paragraph', 'text': '2026. 9. 16.(수)에 실시'}])


def test_build_and_qa():
    out = tempfile.mkdtemp()
    res = make_report(TPL, MD, out, name='e2e', engine='html')
    assert os.path.exists(res['hwpx']) and os.path.exists(res['pdf'])
    assert res['pages'] and res['pages'] >= 2
    assert not res['remaining_issues'], res['remaining_issues']
    with zipfile.ZipFile(res['hwpx']) as z:
        assert z.namelist()[0] == 'mimetype'
        sec = z.read('Contents/section0.xml').decode('utf-8')
        assert '결과 보고' in sec and '2026 ○○ 교원 역량강화 연수 운영 계획' not in sec
        assert 'Ⅴ.' in sec


def test_merged_header_json():
    spec = {'blocks': [
        {'type': 'title', 'text': '병합 표 시험'},
        {'type': 'heading', 'text': 'Ⅰ. 표'},
        {'type': 'table',
         'header': [[{'text': '기수', 'rowspan': 2}, {'text': '강사', 'colspan': 2}],
                    [{'text': '주'}, {'text': '보조'}]],
         'rows': [['1기', '홍길동', '김철수'], ['2기', '이영희', '박민수']],
         'widths': [1, 2, 2]},
        {'type': 'end'}]}
    out = tempfile.mkdtemp()
    res = make_report(TPL, json.dumps(spec, ensure_ascii=False), out, name='merge', engine='html')
    with zipfile.ZipFile(res['hwpx']) as z:
        sec = z.read('Contents/section0.xml').decode('utf-8')
    assert 'rowSpan="2"' in sec and 'colSpan="2"' in sec


def test_fallback_when_no_box_or_table():
    """서식에 박스/표가 없어도 글머리로 대체되어 실패하지 않아야 한다."""
    from hwpx_new.builder import Builder
    b = Builder(TPL)
    b.kit.by_role.pop('box', None)
    b.kit.by_role.pop('table', None)
    els, _ = b.build([{'type': 'title', 'text': 't'},
                      {'type': 'box', 'title': 'x', 'lines': ['a']},
                      {'type': 'table', 'header': ['h1', 'h2'], 'rows': [['a', 'b']]}])
    assert len(els) >= 3 and b.warnings


def test_photos_embedded():
    from hwpx_new.images import prepare_image
    from hwpx_new.validate import validate
    data, ext, w, h = prepare_image(os.path.join(ROOT, 'examples', 'photos', '06_세로회전.jpg'))
    assert (w, h) == (1200, 1600)          # EXIF 회전 보정
    out = tempfile.mkdtemp()
    md = os.path.join(ROOT, 'examples', 'sample_content_photos.md')
    res = make_report(TPL, md, out, name='photo', engine='html')
    assert not validate(res['hwpx']), validate(res['hwpx'])
    with zipfile.ZipFile(res['hwpx']) as z:
        bins = [n for n in z.namelist() if n.startswith('BinData/')]
        sec = z.read('Contents/section0.xml').decode('utf-8')
        hpf = z.read('Contents/content.hpf').decode('utf-8')
    assert len(bins) == 5 and sec.count('<hp:pic ') == 5
    assert all(f'id="image{i}"' in hpf for i in range(1, 6))


def test_missing_photo_is_clear_error():
    out = tempfile.mkdtemp()
    try:
        make_report(TPL, '# t' + chr(10) + '![x](없는사진.jpg)', out, name='x', engine='html')
    except Exception as e:  # noqa
        assert '찾을 수 없' in str(e)
    else:
        raise AssertionError('missing photo should raise')


def _two_section_template():
    """샘플 서식을 2개 구역으로 만든 임시 서식(다구역 서식의 복제·구역 수 보정 시험용)."""
    from hwpx_new.package import Package
    from lxml import etree
    pk = Package(TPL)
    pk.files['Contents/section1.xml'] = pk.files['Contents/section0.xml']
    hpf = etree.fromstring(pk.files['Contents/content.hpf'])
    ns = 'http://www.idpf.org/2007/opf/'
    man = hpf.find('{%s}manifest' % ns)
    item = etree.SubElement(man, '{%s}item' % ns)
    item.set('id', 'section1')
    item.set('href', 'Contents/section1.xml')
    item.set('media-type', 'application/xml')
    spine = hpf.find('{%s}spine' % ns)
    ref = etree.SubElement(spine, '{%s}itemref' % ns)
    ref.set('idref', 'section1')
    ref.set('linear', 'yes')
    pk.files['Contents/content.hpf'] = etree.tostring(hpf, xml_declaration=True, encoding='UTF-8', standalone=True)
    hdr = pk.files['Contents/header.xml'].decode('utf-8').replace('secCnt="1"', 'secCnt="2"')
    pk.files['Contents/header.xml'] = hdr.encode('utf-8')
    path = os.path.join(tempfile.mkdtemp(), 'two.hwpx')
    pk.save(path)
    return path


def test_clone_replace_and_other_section():
    from hwpx_new.builder import Builder
    from hwpx_new.pipeline import build_once
    from hwpx_new.validate import validate
    tpl = _two_section_template()
    out = os.path.join(tempfile.mkdtemp(), 'c.hwpx')
    specs = [{'type': 'clone', 'from': 0, 'to': 1, 'replace': {'○○교육지원청': '평택교육지원청'}},
             {'type': 'clone', 'section': 1, 'from': 3, 'replace': {'연수 개요': '대회 개요'}},
             {'type': 'like', 'from': 17, 'texts': ['  ● 새 글머리 문장']}]
    b, probes = build_once(tpl, specs, set(), 0, out, 't')
    assert not validate(out), validate(out)
    with zipfile.ZipFile(out) as z:
        hdr = z.read('Contents/header.xml').decode('utf-8')
        sec = z.read('Contents/section0.xml').decode('utf-8')
        assert 'secCnt="1"' in hdr and 'Contents/section1.xml' not in z.namelist()
    assert '평택교육지원청' in sec and '대회 개요' in sec and '새 글머리 문장' in sec


def test_table_proto_and_floating():
    from hwpx_new.builder import Builder
    b = Builder(TPL)
    b._compact = 0
    rows = [[f'항목{i}', '긴 내용 ' * 30] for i in range(40)]
    el = b.make_table({'header': ['항목', '내용'], 'rows': rows, 'widths': [1, 4]})
    from hwpx_new.package import HP
    assert el.find('.//' + HP + 'pos').get('treatAsChar') == '0'      # 쪽에 가까운 큰 표는 떠 있는 표
    el2 = b.make_table({'header': ['항목', '내용'], 'rows': rows[:2], 'widths': [1, 4], 'proto': 10})
    assert el2.find('.//' + HP + 'tbl') is not None and el2.find('.//' + HP + 'tbl').get('rowCnt') == '3'   # proto 지정 표


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('OK', name)
