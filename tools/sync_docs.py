# -*- coding: utf-8 -*-
"""hwpx_new/data/AGENTS.md(단일 원본)에서 각 AI 용 지침 파일을 만든다: AGENTS.md · CLAUDE.md · GEMINI.md · copilot · cursor · skill."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hwpx_new import setup_cmd  # noqa: E402

body = setup_cmd.agents_text()
files = {
    'AGENTS.md': body,
    'CLAUDE.md': body,
    'GEMINI.md': body,
    '.github/copilot-instructions.md': body,
    '.cursor/rules/hwpx-new.mdc': '---\ndescription: 한글(HWPX) 서식으로 새 문서(HWPX+PDF)를 만드는 작업 지침(사진 삽입·복제 포함)\nalwaysApply: false\nglobs: ["**/*.hwpx", "**/*.hwp"]\n---\n\n' + body,
    'skill/hwpx-new/SKILL.md': setup_cmd.skill_text(),
}
for rel, text in files.items():
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('wrote', rel)
