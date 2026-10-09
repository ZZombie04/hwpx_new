# -*- coding: utf-8 -*-
"""장편 보고서(report) 테스트: 글 다듬기 · 통계(알려진 값) · 도표 · @stats · 자료 도표 · 점검기 · 빌드(내장 렌더러, 한글 없이도 통과)."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hwpx_new import charts, stats, textfix  # noqa: E402
from hwpx_new.report import Builder, read_manuscript  # noqa: E402
from hwpx_new.report_check import check, citations, parse_reference  # noqa: E402

EX = os.path.join(ROOT, 'hwpx_new', 'data', 'report_example')
NB = chr(0xA0)


# ---------------------------------------------------------------- 글 다듬기
def test_josa_after_numbers_and_refs():
    assert textfix.polish('표 Ⅳ-3과 그림 2를 보면 0.62였다') == '표 Ⅳ-3과 그림 2를 보면 0.62였다'
    assert textfix.fix_ref_josa('표 Ⅴ-1와') == '표 Ⅴ-1과'
    assert textfix.fix_ref_josa('그림 2을') == '그림 2를'
    assert textfix.fix_num_josa('3.85였다') == '3.85였다' and textfix.fix_num_josa('0.33이었다') == '0.33이었다'
    assert textfix.fix_num_josa('1.00였다') == '1.00이었다'
    assert textfix.fix_paren_josa('(교육부, 2024)는') == '(교육부, 2024)는'
    assert textfix.fix_paren_josa('서경혜(2009)는') == '서경혜(2009)는'


def test_smart_quotes_only_in_korean():
    assert textfix.smart_quotes("'수업 나눔'이다") == '‘수업 나눔’이다'
    assert textfix.smart_quotes("Cohen's d") == "Cohen's d"
    assert textfix.smart_quotes("Hedges' g 를 씀") == "Hedges' g 를 씀"


def test_stat_expressions_are_bound():
    s = textfix.polish('(t(31) = 6.16, p < .001, d = 1.09, 95% 신뢰구간 [0.44, 0.88]), g 0.33')
    assert f't(31){NB}={NB}6.16' in s and f'p{NB}<{NB}.001' in s and f'[0.44,{NB}0.88]' in s and f'g{NB}0.33' in s
    assert textfix.polish('집단 a = b 이다') == '집단 a = b 이다'          # 숫자가 아니면 그대로


# ---------------------------------------------------------------- 통계(교과서·scipy 로 확인한 값)
def test_t_distribution():
    assert abs(stats.t_p_two(2.0, 10) - 0.07338803477074) < 1e-9
    assert abs(stats.t_crit(31) - 2.0395134463964) < 1e-9
    assert stats.fmt_p(0.0004) == '< .001' and stats.fmt_p(0.0234) == '= .023'
    assert stats.rd(0.125) == '0.13' and stats.rd(41.25, 1) == '41.3'      # 사사오입


def test_paired_welch_alpha_kappa_corr():
    pre = [3, 4, 2, 5, 3, 4, 3, 2]
    post = [4, 5, 3, 5, 4, 5, 4, 3]
    r = stats.paired(pre, post)
    assert r['n'] == 8 and abs(r['diff'] - 0.875) < 1e-12 and r['up'] == 7 and r['same'] == 1
    assert abs(r['t'] - 7.0) < 1e-9 and abs(r['dz'] - 2.4748737341529) < 1e-9
    w = stats.welch([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert abs(w['t'] - 1.8973665961010) < 1e-9 and abs(w['df'] - 5.8823529411765) < 1e-9
    a = stats.cronbach([[1, 2, 3], [2, 3, 4], [3, 3, 5], [4, 5, 5]])
    assert abs(a['alpha'] - 0.9485294117647) < 1e-9          # 3/2 × (1 − 4.1667/11.3333)
    k = stats.kappa([1, 2, 3, 1, 2], [1, 2, 3, 2, 2], weights=None)
    assert abs(k['kappa'] - 0.6875) < 1e-9 and abs(k['agree'] - 0.8) < 1e-12
    c = stats.pearson([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
    assert abs(c['r'] - 0.7745966692415) < 1e-9


def test_desc_freq_where_and_tokens():
    d = stats.describe(['1', '2', '3', '4', '', 'x'])
    assert d['n'] == 4 and abs(d['m'] - 2.5) < 1e-12 and d['median'] == 2.5
    f = stats.freq(['1', '1', '2', '3'], ['가', '가', '가', '나'])
    t = stats.tokens(f, 'lv')
    assert t['lv.가.1'] == '66.7' and t['lv.가.1.n'] == '2' and t['lv.나.3'] == '100.0'
    toks, summary = stats.run_line('paired data.csv --pre 성찰사전 --post 성찰사후 --where 경력=초임 --prefix st', EX)
    assert toks['st.n'] == '9' and toks['st.t'] == '5.02' and toks['st.p'] == '= .001' and 't(8) = 5.02' in summary


# ---------------------------------------------------------------- 도표
def test_all_chart_types_render():
    out = tempfile.mkdtemp()
    specs = {
        'bar': {'rows': [['4월', 12], ['5월', 18]]}, 'hbar': {'rows': [['가', 34.4], ['나', 81.3]], 'max': 100},
        'group': {'rows': [['초임', '3.19', '4.11'], ['원숙', '3.22[3.0,3.4]', '3.68']], 'legend': '사전,사후', 'min': 1, 'max': 5},
        'dumbbell': {'rows': [['성찰', 3.19, 3.85, 'd 1.09']], 'min': 1, 'max': 5},
        'stack': {'rows': [['1학기', 41.3, 43.8, 15.0]], 'legend': '1,2,3'},
        'effect': {'rows': [['성찰', 1.09, 'n=32'], ['학생', 0.33]]}, 'hist': {'rows': [['0~1', 3], ['1~2', 5]]},
        'scatter': {'rows': [[1, 2], [2, 3], [3, 5], [4, 4]]}, 'line': {'rows': [['2024', 1, 2], ['2025', 3, 2]]},
        'timeline': {'rows': [['2025.', '시범'], ['2026.', '운영/확산', '예정']], 'highlight': 2},
        'steps': {'rows': [['준비', '3월', '실태/분석'], ['실행', '4~10월', '운영']]},
        'cycle': {'rows': [['공개', '10분'], ['기록', '1쪽'], ['대화', '질문']], 'center': '공동체'},
    }
    from PIL import Image
    for k, s in specs.items():
        p = charts.render({'type': k, **s}, os.path.join(out, k + '.png'))
        im = Image.open(p)
        assert im.size[0] == charts.DEFAULT_W * 2 and im.size[1] > 200, k


# ---------------------------------------------------------------- 원고 읽기·토큰·자료 도표
def test_example_manuscript_resolves():
    ms = read_manuscript(os.path.join(EX, 'report.txt'))
    assert len(ms.stats) >= 10 and ms.facts['ref.t'] == '6.16' and ms.facts['com.d'] == '1.42'
    assert ms.facts['lv.1학기.1'] == '41.3' and ms.facts['visit.m1'] == '4.3'
    B = Builder(ms, work_dir=tempfile.mkdtemp())
    for b in ms.body:
        if b[0] == 'p':
            B.sub(b[1])
    assert not [m for m in B.missing if not m.startswith('pages.')]
    assert B.refs['표:overview'] == '표 Ⅴ-1' and B.refs['그림:dose'] == '그림 Ⅴ-3'
    rows = B._data_rows('stage', {'data': 'data.csv', 'by': '경력', 'order': '초임,중견,원숙', 'y': '성찰사전,성찰사후'})
    assert rows == [['초임(n=9)', '3.19', '4.11'], ['중견(n=13)', '3.18', '3.81'], ['원숙(n=10)', '3.22', '3.68']]
    rows = B._data_rows('rubric', {'data': 'ratings.csv', 'col': '평정자1', 'by': '학기'})
    assert rows[0] == ['1학기', '41.3', '43.8', '15.0'] and rows[1][0] == '2학기'
    rows = B._data_rows('h', {'data': 'data.csv', 'col': '성찰변화', 'bins': '-1,0,1,2'})
    assert sum(int(r[1]) for r in rows) == 32


def test_checker_on_example_and_on_mistakes():
    ms = read_manuscript(os.path.join(EX, 'report.txt'))
    assert [x for x in check(ms) if x[0] == '오류'] == []
    bad = os.path.join(tempfile.mkdtemp(), 'r.txt')
    open(bad, 'w', encoding='utf-8').write(
        '---\ntitle: 시험\n---\n@body\n@ch Ⅰ | 개요\n'
        '이 방법은 효과를 입증하였다(홍길동, 2020). 점수가 유의하게 올랐다. 2026. 11. 5.(수)에 모였다. {{없는.값}}\n\n'
        '@table t1 | 표 | widths=1,1\n| 가 | 나 |\n| 1 | 2 |\n'
        '@refs\n@r 김철수(2019). 제목. 학술지, 1(1), 1-2.\n')
    iss = check(read_manuscript(bad))
    text = '\n'.join(m for _, m in iss)
    errs = [m for lv, m in iss if lv == '오류']
    assert any('홍길동' in m for m in errs) and any('요일' in m for m in errs) and any('없는.값' in m for m in errs)
    assert '입증' in text and '유의' in text and '김철수' in text and 't1' in text


def test_sloppy_manuscript_still_builds_and_is_reported():
    """가벼운 모델이 흔히 내는 실수(@end 빠짐·모르는 표시·칸 수 틀린 표·없는 사진·없는 열)는 멈추지 않고 점검이 알려 준다."""
    from hwpx_new.report import build_report
    d = tempfile.mkdtemp()
    import shutil
    shutil.copyfile(os.path.join(EX, 'data.csv'), os.path.join(d, 'data.csv'))
    src = os.path.join(d, 'report.txt')
    open(src, 'w', encoding='utf-8').write(
        '---\ntitle: 시험 보고서\n---\n'
        '@stats paired data.csv --pre 없는열 --post 성찰사후 --prefix bad\n'
        '@stats paired data.csv --pre 성찰사전 --post 성찰사후 --prefix ref\n'
        '@body\n@ch Ⅰ | 개요\n@sec 1 | 결과\n평균은 {{ref.m0}}점에서 {{ref.m1}}점으로 올랐다({표:t1}, {그림:c1}, {사진:p1}).\n\n'
        '@box 요약 | tone=accent\n○ 상자 줄\n'
        '@chart c1 | 도표 | type=bar\n가 | 1\n나 | 2\n@end\n'
        '@note 이런 표시는 없다\n'
        '@table t1 | 표 | widths=1,1,1\n| 가 | 나 | 다 |\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |\n'
        '@photos p1 | 사진 | photos/없음.jpg ; 설명\n')
    res = build_report(src, os.path.join(d, 'out'), engine='html', max_passes=1)
    assert os.path.exists(res['hwpx'])
    text = '\n'.join(f'{lv} {m}' for lv, m in res['issues'])
    assert '@box 요약 에 @end 가 없어' in text and '모르는 표시 "@note"' in text
    assert '칸 수를 3개로 맞춰' in text and '없는열' in text and '사진 파일:photos/없음.jpg' in text
    assert any(lv == '오류' for lv, _ in res['issues'])


def test_difference_columns_and_low_alpha_warning():
    toks, _ = stats.run_line('corr data.csv --x 공개참관횟수 --y 성찰사후-성찰사전 --prefix ch', EX)
    assert toks['ch.r'] == '.51'                                       # 미리 만든 '성찰변화' 열과 같은 결과
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'a.csv'), 'w', encoding='utf-8').write('q1,q2,q3\n1,5,2\n2,3,2\n3,4,3\n4,1,3\n5,2,4\n')
    src = os.path.join(d, 'r.txt')
    open(src, 'w', encoding='utf-8').write('---\ntitle: 시험\n---\n@stats alpha a.csv --items q1,q2,q3 --prefix a\n'
                                          '@body\n@ch Ⅰ | 개요\n신뢰도는 {{a.alpha}}였다.\n')
    iss = check(read_manuscript(src))
    assert any(lv == '주의' and '신뢰도가 낮음' in m for lv, m in iss)


def test_chart_ticks_are_round_numbers():
    assert charts._ticks(-1, 10) == [0, 5, 10] and charts._snap(-1, 8) == (-2, 8)
    assert charts._ticks(1, 5) == [1, 2, 3, 4, 5] and charts._ticks(0, 2.0) == [0, 0.5, 1.0, 1.5, 2.0]


def test_reference_parsing():
    assert parse_reference('이윤식, 강재춘(2005). 제목.')['authors'] == ['이윤식', '강재춘']
    assert parse_reference('Guskey, T. R. (2002). Title.')['authors'] == ['Guskey']
    assert parse_reference('「연구학교에 관한 규칙」(교육부령).')['law'] == '「연구학교에 관한 규칙」'
    got = citations('선행 연구(서경혜, 2009; 이석열, 2018)와 김병찬(2009)의 연구')
    assert {(a, y) for a, y, _, _ in got} == {('서경혜', '2009'), ('이석열', '2018'), ('김병찬', '2009')}


# ---------------------------------------------------------------- 빌드(내장 렌더러: 한글이 없어도 통과)
def test_build_example_with_builtin_renderer():
    from hwpx_new.report import build_report
    out = tempfile.mkdtemp()
    res = build_report(os.path.join(EX, 'report.txt'), out, engine='html', max_passes=3)
    assert os.path.exists(res['hwpx']) and res['pdf'] and os.path.exists(res['pdf'])
    assert not res['missing'] and not [x for x in res['issues'] if x[0] == '오류']
    assert res['info']['body'] >= 10 and res['info']['front'] >= 4
    with zipfile.ZipFile(res['hwpx']) as z:
        names = z.namelist()
        sec = z.read('Contents/section0.xml').decode('utf-8')
    assert sum(1 for n in names if n.startswith('BinData/')) >= 15          # 사진 12 + 도표 8 + 표지
    assert 'pageBreak="TABLE"' in sec or 'treatAsChar="1"' in sec
    assert '<hp:nbSpace/>' in sec and 'pageNum' in sec and 'ROMAN_SMALL' in sec


def test_cli_report_init_and_prompt():
    d = tempfile.mkdtemp()
    env = {**os.environ, 'PYTHONUTF8': '1'}
    r = subprocess.run([sys.executable, '-m', 'hwpx_new', 'report', 'init', os.path.join(d, 'ex')], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', env=env)
    assert r.returncode == 0 and os.path.exists(os.path.join(d, 'ex', 'report.txt'))
    assert len(os.listdir(os.path.join(d, 'ex', 'photos'))) == 12
    r = subprocess.run([sys.executable, '-m', 'hwpx_new', 'report', 'init', os.path.join(d, 'ex')], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', env=env)
    assert r.returncode == 1 and '--force' in r.stdout                     # 덮어쓰지 않음
    p = os.path.join(d, 'prompt.txt')
    r = subprocess.run([sys.executable, '-m', 'hwpx_new', 'report', 'prompt', '가나초 독서 연구', '--data',
                        os.path.join(EX, 'data.csv'), '-o', p], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', env=env)
    text = open(p, encoding='utf-8').read()
    assert r.returncode == 0 and '가나초 독서 연구' in text and '성찰사전1' in text and '@stats' in text and '{{ref.m0}}' in text


def test_mcp_lists_report_tools():
    msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'hwpx_stats', 'arguments': {
                'command': 'corr data.csv --x 공개참관횟수 --y 성찰변화 --prefix dose', 'base_dir': EX}}}]
    p = subprocess.run([sys.executable, '-m', 'hwpx_new.mcp_server'], input='\n'.join(json.dumps(m) for m in msgs) + '\n',
                       capture_output=True, text=True, encoding='utf-8', cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1'})
    out = [json.loads(x) for x in p.stdout.splitlines()]
    names = {t['name'] for t in out[1]['result']['tools']}
    assert {'hwpx_report_build', 'hwpx_report_check', 'hwpx_report_guide', 'hwpx_report_example', 'hwpx_stats', 'hwpx_chart'} <= names
    assert 'r = .51' in out[2]['result']['content'][0]['text']
