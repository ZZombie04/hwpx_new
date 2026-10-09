# -*- coding: utf-8 -*-
"""AI 프로그램 연결 도우미: `hwpx-new setup` 한 번으로 설치된 AI 프로그램(Claude·Codex·Gemini·Cursor 등)에 MCP 를 등록한다.

- 설정 파일을 고치기 전에 항상 백업(.hwpx_new.bak)을 만들고, 이미 등록돼 있으면 건드리지 않는다.
- 등록에는 이 파이썬의 '절대 경로'를 쓰므로 PATH 설정이 필요 없다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

NAME = 'hwpx_new'


def _home(home=None):
    return home or os.path.expanduser('~')


def server_entry():
    return {'command': sys.executable, 'args': ['-m', 'hwpx_new.mcp_server']}


def client_list(home=None):
    h = _home(home)
    appdata = (os.path.join(h, 'AppData', 'Roaming') if home else
               os.environ.get('APPDATA') or os.path.join(h, 'AppData', 'Roaming'))
    if sys.platform == 'darwin':
        desktop = os.path.join(h, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json')
    elif sys.platform == 'win32':
        desktop = os.path.join(appdata, 'Claude', 'claude_desktop_config.json')
    else:
        desktop = os.path.join(h, '.config', 'Claude', 'claude_desktop_config.json')
    return [
        {'id': 'claude-code', 'name': 'Claude Code', 'kind': 'cli', 'probe': os.path.join(h, '.claude')},
        {'id': 'claude-desktop', 'name': 'Claude Desktop', 'kind': 'json', 'path': desktop},
        {'id': 'codex', 'name': 'Codex CLI', 'kind': 'toml', 'path': os.path.join(h, '.codex', 'config.toml')},
        {'id': 'gemini', 'name': 'Gemini CLI', 'kind': 'json', 'path': os.path.join(h, '.gemini', 'settings.json')},
        {'id': 'cursor', 'name': 'Cursor', 'kind': 'json', 'path': os.path.join(h, '.cursor', 'mcp.json')},
        {'id': 'windsurf', 'name': 'Windsurf', 'kind': 'json',
         'path': os.path.join(h, '.codeium', 'windsurf', 'mcp_config.json')},
    ]


def installed(c):
    p = c.get('path') or c.get('probe')
    return bool(p) and os.path.exists(os.path.dirname(p) if c.get('path') else p)


def _backup(path):
    bak = path + '.hwpx_new.bak'
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copyfile(path, bak)


def register_json(path, dry=False):
    data = {}
    if os.path.exists(path):
        raw = open(path, encoding='utf-8-sig').read().strip()
        if raw:
            data = json.loads(raw)
    servers = data.setdefault('mcpServers', {})
    if NAME in servers and servers[NAME].get('command') == sys.executable:
        return 'already'
    if not dry:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _backup(path)
        servers[NAME] = server_entry()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return 'added'


def register_toml(path, dry=False):
    text = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    if f'[mcp_servers.{NAME}]' in text:
        return 'already'
    block = f"\n[mcp_servers.{NAME}]\ncommand = '{sys.executable}'\nargs = ['-m', 'hwpx_new.mcp_server']\n"
    if not dry:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _backup(path)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(block)
    return 'added'


def register_claude_code(dry=False, home=None):
    exe = shutil.which('claude')
    if not exe:
        # 데스크톱 앱·IDE 확장에 들어 있는 Claude Code 는 `claude` 명령이 PATH 에 없다 → 사용자 설정(~/.claude.json)에 직접 등록
        cfg = os.path.join(_home(home), '.claude.json')
        if os.path.exists(cfg):
            return register_json(cfg, dry)
        return 'no-cli'
    if dry:
        return 'added'
    try:
        r = subprocess.run([exe, 'mcp', 'add', '--scope', 'user', NAME, '--', sys.executable, '-m',
                            'hwpx_new.mcp_server'], capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa
        return f'fail: {e}'
    out = (r.stdout or '') + (r.stderr or '')
    if r.returncode == 0:
        return 'added'
    if 'already exists' in out:
        return 'already'
    return 'fail: ' + out.strip()[:120]


DATA = os.path.join(os.path.dirname(__file__), 'data')
SKILL_FRONT = """---
name: hwpx-new
description: 한글(HWPX) 문서를 만들고 고친다 — 서식 그대로 새 문서(계획서→결과보고서, 작년→올해), Ⅰ→■→❍→- 체계의 정돈된 계획서·안내문, 공문(내부 기안문·학교로 나갈 겉공문, 표·QR 포함), 사용자가 한글에서 손본 파일의 부분 수정(손본 자간·서식 보존), 행사명 같은 글자만 바꾸기, 연구학교 결과보고서·연구보고서 같은 장편 보고서(차례·표 차례·통계 검정·도표 자동, 20~60쪽), 조판 점검. 사용자가 .hwpx/.hwp 파일을 주며 "이 양식으로 만들어줘", "결과보고서로 바꿔줘", "겉공문 만들어줘", "계획서에 ○○ 넣어줘", "명칭만 바꿔줘"라고 하거나, "연구학교 결과보고서를 한글로 써줘"처럼 장편 보고서를 요청할 때 사용.
---

"""


def agents_text():
    return open(os.path.join(DATA, 'AGENTS.md'), encoding='utf-8').read()


def skill_text():
    return SKILL_FRONT + agents_text()


def install_skill(home=None, dry=False):
    """Claude Code 용 스킬(SKILL.md)을 ~/.claude/skills/hwpx-new 에 만든다."""
    dst_dir = os.path.join(_home(home), '.claude', 'skills', 'hwpx-new')
    dst = os.path.join(dst_dir, 'SKILL.md')
    text = skill_text()
    if os.path.exists(dst) and open(dst, encoding='utf-8').read() == text:
        return 'already'
    if not dry:
        os.makedirs(dst_dir, exist_ok=True)
        with open(dst, 'w', encoding='utf-8') as f:
            f.write(text)
    return 'added'


LABEL = {'added': '연결했습니다', 'already': '이미 연결돼 있습니다', 'no-cli': '`claude` 명령을 찾지 못함(건너뜀)'}


def run_setup(only=None, yes=False, dry=False, home=None, include_missing=False, ask=input):
    """설치된 AI 프로그램을 찾아 등록. 반환: (메시지 목록, 등록 수)"""
    msgs, n = [], 0
    clients = client_list(home)
    for c in clients:
        if only and c['id'] not in only:
            continue
        if not (installed(c) or include_missing or only):
            continue
        if not yes and not dry:
            try:
                ans = ask(f'{c["name"]} 에 hwpx_new 를 연결할까요? [Y/n] ').strip().lower()
            except EOFError:
                ans = 'y'
            if ans in ('n', 'no', 'ㅜ'):
                msgs.append(f'- {c["name"]}: 건너뜀')
                continue
        try:
            if c['kind'] == 'cli':
                res = register_claude_code(dry, home)
            elif c['kind'] == 'json':
                res = register_json(c['path'], dry)
            else:
                res = register_toml(c['path'], dry)
        except Exception as e:  # noqa
            res = f'fail: {e}'
        if res == 'added':
            n += 1
        msgs.append(f'- {c["name"]}: ' + LABEL.get(res, res) + ('' if res != 'added' or dry else ''))
    if not msgs:
        msgs.append('설치된 AI 프로그램을 찾지 못했습니다. `hwpx-new mcp-config` 로 설정 문구를 확인해 직접 붙여 넣으세요.')
    return msgs, n
