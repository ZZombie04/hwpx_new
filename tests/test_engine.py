# -*- coding: utf-8 -*-
"""엔진 단위 테스트: 글머리 인식, 글 바꾸기(글자 모양 유지), 뼈대 Markdown 왕복, 설치 도우미, 한글 자동화 스크립트 문법."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lxml import etree  # noqa: E402

from hwpx_new.analyze import analyze, bullet_marker, heading_class, scaffold_markdown  # noqa: E402
from hwpx_new.builder import set_text_keep, transfer_pieces  # noqa: E402
from hwpx_new.mdparse import parse_markdown  # noqa: E402
from hwpx_new.package import HP, Package  # noqa: E402

TPL = os.path.join(ROOT, 'examples', 'sample_template.hwpx')


def test_bullet_marker_detects_symbols_and_jamo():
    assert bullet_marker('ㅇ 자율 참여').strip() == 'ㅇ'
    assert bullet_marker(' - 내용').strip() == '-'
    assert bullet_marker('□ 운영 원칙').strip() == '□'
    assert bullet_marker('※ 참고') and bullet_marker('◦ 가')
    assert not bullet_marker('1. 번호')
    assert not bullet_marker('「RAS 경기」 는')
    assert not bullet_marker('일반 문장입니다.')
    assert heading_class('Ⅰ. 개요') == 'roman' and heading_class('1. 개요') == 'num' and heading_class('가. 개요') == 'hangul'


def _p(runs):
    ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    body = ''.join(f'<hp:run charPrIDRef="{c}"><hp:t>{t}</hp:t></hp:run>' for c, t in runs)
    return etree.fromstring(f'<hp:p {ns}>{body}</hp:p>')


def test_set_text_keep_preserves_unchanged_word_styles():
    p = _p([('1', '접속 주소: '), ('2', 'https://a.kr'), ('1', ' 입니다')])
    set_text_keep(p, '접속 주소: https://b.kr 입니다')
    texts = [(r.get('charPrIDRef'), ''.join(r.itertext())) for r in p.findall(HP + 'run')]
    assert texts[0] == ('1', '접속 주소: ') and texts[1][0] == '2' and texts[2] == ('1', ' 입니다')
    assert 'b.kr' in texts[1][1] and 'a.kr' not in texts[1][1]


def test_transfer_pieces_follows_label_colon_pattern():
    assert transfer_pieces(['가. 공통 기반: ', '긴 설명'], '가. 새 제목: 새 설명입니다') == ['가. 새 제목: ', '새 설명입니다']
    assert transfer_pieces(['○ ', '항목: ', '값'], '○ 이름: 홍길동') == ['○ ', '이름: ', '홍길동']
    assert transfer_pieces(['라벨: ', '값'], '구분자 없음') is None


def test_skeleton_roundtrip_is_faithful_and_parseable():
    bp = analyze(TPL)
    md = scaffold_markdown(bp)
    blocks = parse_markdown(md)
    types = [b['type'] for b in blocks]
    assert types[0] == 'title' and 'heading' in types and 'table' in types and 'box' in types
    from hwpx_new.selfcheck import run_selfcheck
    r = run_selfcheck(TPL)
    assert r['score'] >= 75, r['stats']
    assert r['matched'] >= 14


def test_markdown_tags_cover_like_clone_json():
    md = '\n'.join([
        '## {H2} Ⅰ. 제목',
        '- {B2} 글머리',
        '<!-- class: T3 -->',
        '| a | b |',
        '|---|---|',
        '| 1 | 2 |',
        ':::cover',
        '칸1',
        '칸2',
        ':::',
        '@like 34 | 새 글',
        '@clone 7-9',
        '```json',
        '{"type": "clone", "from": 3, "paras": ["x", "y"]}',
        '```',
    ])
    b = parse_markdown(md)
    assert b[0] == {'type': 'heading', 'text': 'Ⅰ. 제목', 'class': 'H2'}
    assert b[1]['class'] == 'B2' and b[1]['level'] == 1
    assert b[2]['type'] == 'table' and b[2]['class'] == 'T3'
    assert b[3]['type'] == 'title' and b[3]['fields'] == ['칸1', '칸2']
    assert b[4] == {'type': 'like', 'from': 34, 'text': '새 글'}
    assert b[5] == {'type': 'clone', 'from': 7, 'to': 9}
    assert b[6]['paras'] == ['x', 'y']


def test_inline_bold_creates_bold_char_variant():
    from hwpx_new.builder import Builder
    b = Builder(TPL)
    els, _ = b.build([{'type': 'title', 'text': 't'}, {'type': 'heading', 'text': 'Ⅰ. 가'},
                      {'type': 'bullet', 'text': '앞 **굵은말** 뒤', 'level': 1}])
    txt = etree.tostring(els[-1]).decode('utf-8')
    assert '**' not in txt and txt.count('<hp:run') >= 3


def test_foreign_generator_marks_are_scrubbed():
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'a.hwpx')
    with zipfile.ZipFile(TPL) as z, zipfile.ZipFile(src, 'w') as o:
        for i in z.infolist():
            data = z.read(i.filename)
            if i.filename == 'Contents/content.hpf':
                tool = ('Kor' + 'doc').encode()
                data = data.replace(b'<opf:metadata>', b'<opf:metadata><opf:meta name="generator" content="' + tool + b'"/>'
                                    b'<opf:meta name="' + tool.lower() + b'-layout" content="x"/>')
            o.writestr(i.filename, data)
    pk = Package(src)
    out = os.path.join(d, 'b.hwpx')
    pk.save(out)
    with zipfile.ZipFile(out) as z:
        allt = b''.join(z.read(n) for n in z.namelist() if not n.startswith('BinData')).lower()
    assert ('kor' + 'doc').encode() not in allt


def test_table_same_shape_keeps_row_count():
    from hwpx_new.builder import Builder
    bp = analyze(TPL)
    tb = next(b for b in bp.blocks if b.role == 'table' and b.info['rows'] == 10)
    b = Builder(TPL)
    hdr = [c['text'] for c in tb.info['cells'] if c['r'] == 0]
    rows = [[c['text'] for c in tb.info['cells'] if c['r'] == r] for r in range(1, tb.info['rows'])]
    el = b.make_table({'header': hdr, 'rows': rows, 'class': tb.cls})
    assert el.find('.//' + HP + 'tbl').get('rowCnt') == '10'


def test_setup_registers_clients_into_fake_home():
    from hwpx_new import setup_cmd
    home = tempfile.mkdtemp()
    for d in ('.codex', '.gemini', '.cursor'):
        os.makedirs(os.path.join(home, d))
    msgs, n = setup_cmd.run_setup(yes=True, home=home)
    assert n >= 3, msgs
    cfg = json.load(open(os.path.join(home, '.cursor', 'mcp.json'), encoding='utf-8'))
    assert cfg['mcpServers']['hwpx_new']['args'] == ['-m', 'hwpx_new.mcp_server']
    assert '[mcp_servers.hwpx_new]' in open(os.path.join(home, '.codex', 'config.toml'), encoding='utf-8').read()
    _msgs2, n2 = setup_cmd.run_setup(yes=True, home=home)       # 두 번째는 이미 연결됨
    assert n2 == 0
    gp = os.path.join(home, '.gemini', 'settings.json')          # 기존 설정은 보존
    json.dump({'theme': 'x', 'mcpServers': {'other': {'command': 'y'}}}, open(gp, 'w'))
    setup_cmd.run_setup(yes=True, home=home, only=['gemini'])
    g = json.load(open(gp, encoding='utf-8'))
    assert g['theme'] == 'x' and 'other' in g['mcpServers'] and 'hwpx_new' in g['mcpServers']


def test_setup_claude_code_without_cli_uses_user_config(monkeypatch):
    """데스크톱 앱·IDE 의 Claude Code 는 `claude` 명령이 없다 → ~/.claude.json 에 직접 등록(다른 설정은 보존)."""
    from hwpx_new import setup_cmd
    monkeypatch.setattr(setup_cmd.shutil, 'which', lambda name: None)
    home = tempfile.mkdtemp()
    os.makedirs(os.path.join(home, '.claude'))
    cp = os.path.join(home, '.claude.json')
    json.dump({'numStartups': 3, 'mcpServers': {'other': {'command': 'x'}}}, open(cp, 'w'))
    msgs, n = setup_cmd.run_setup(yes=True, home=home, only=['claude-code'])
    d = json.load(open(cp, encoding='utf-8'))
    assert n == 1 and d['numStartups'] == 3 and 'other' in d['mcpServers'] and 'hwpx_new' in d['mcpServers'], msgs
    assert os.path.exists(cp + '.hwpx_new.bak')


def test_skill_text_has_front_matter():
    from hwpx_new import setup_cmd
    t = setup_cmd.skill_text()
    assert t.startswith('---\nname: hwpx-new') and '## 0. 작업 고르기' in t and 'gongmun' in t


def test_hancom_powershell_scripts_parse():
    if sys.platform != 'win32':
        return
    from hwpx_new import hancom
    for name in ('RUN_PS', 'APPROVE_PS'):
        d = tempfile.mkdtemp()
        f = os.path.join(d, name + '.ps1')
        with open(f, 'w', encoding='utf-8-sig') as fh:
            fh.write(getattr(hancom, name))
        cmd = ('$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("%s",[ref]$t,[ref]$e);'
               'if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }' % f)
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True, errors='replace')
        assert r.returncode == 0, (name, r.stdout, r.stderr)


def test_cli_help_for_every_command():
    """모든 하위 명령의 도움말이 깨지지 않아야 한다(% 같은 글자로 argparse 가 죽는 사고 방지)."""
    from hwpx_new.cli import build_parser
    ap = build_parser()
    ap.format_help()
    sub = next(a for a in ap._actions if a.__class__.__name__ == '_SubParsersAction')
    for name, p in sub.choices.items():
        assert p.format_help(), name


def test_cli_entrypoints_run_as_subprocess():
    for args in (['--help'], ['doctor'], ['format']):
        r = subprocess.run([sys.executable, '-m', 'hwpx_new'] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONUTF8': '1'})
        assert r.returncode in (0, 1) and 'Traceback' not in r.stderr, (args, r.stderr[-400:])
