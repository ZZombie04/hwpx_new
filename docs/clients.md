# AI 프로그램별 연결 방법

## 가장 쉬운 방법: 자동 연결

```bash
hwpx-new setup            # 설치된 AI 프로그램을 찾아 하나씩 물어보고 연결
hwpx-new setup --yes      # 묻지 않고 모두 연결
hwpx-new setup --dry-run  # 고치지 않고 무엇을 할지만 보기
hwpx-new setup --skill    # Claude Code 스킬(SKILL.md)도 설치
```

- Claude Code · Claude Desktop · Codex CLI · Gemini CLI · Cursor · Windsurf 를 자동으로 찾습니다.
- 설정 파일은 고치기 전에 `…hwpx_new.bak` 으로 **백업**하고, 이미 연결돼 있으면 건드리지 않으며, 다른 MCP 설정은 그대로 둡니다.
- 설정에는 이 파이썬의 **전체 경로**가 들어가므로 PATH 설정이 필요 없습니다.
- 끝나면 **AI 프로그램을 완전히 종료했다가 다시 실행**해야 도구가 나타납니다.

## 직접 붙여 넣기

`hwpx-new mcp-config` 를 실행하면 **내 컴퓨터의 파이썬 경로가 들어간 설정**이 그대로 출력됩니다. 공통 JSON:

```json
{
  "mcpServers": {
    "hwpx_new": {
      "command": "C:/…/python.exe",
      "args": ["-m", "hwpx_new.mcp_server"]
    }
  }
}
```

| 프로그램 | 붙이는 곳 |
|---|---|
| **Claude Code** | `claude mcp add --scope user hwpx_new -- <python 경로> -m hwpx_new.mcp_server` |
| **Claude Desktop** | 설정 → 개발자 → 구성 편집(`claude_desktop_config.json`)에 공통 JSON |
| **Cursor** | `~/.cursor/mcp.json` (또는 프로젝트 `.cursor/mcp.json`)에 공통 JSON |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` 에 공통 JSON |
| **Antigravity** | MCP 서버 관리 → 설정 파일에 공통 JSON |
| **Codex CLI** | `~/.codex/config.toml` 에 아래 추가 |
| **Gemini CLI** | `~/.gemini/settings.json` 의 `mcpServers` 에 공통 JSON |
| **VS Code (Copilot)** | `.vscode/mcp.json` 에 `{"servers": {"hwpx_new": {"command": "<python 경로>", "args": ["-m","hwpx_new.mcp_server"]}}}` |

Codex `config.toml`:

```toml
[mcp_servers.hwpx_new]
command = 'C:\...\python.exe'
args = ['-m', 'hwpx_new.mcp_server']
```

## MCP 도구 목록

| 도구 | 역할 |
|---|---|
| `hwpx_start_here` | 사용 순서와 규칙 안내(AI 가 가장 먼저 호출) |
| `hwpx_doctor` | PDF 변환 엔진·한글 자동화 점검 |
| `hwpx_format_guide` | 내용 작성 문법 |
| `hwpx_analyze` | 서식 분석(서식 종류·블록) + 뼈대 Markdown |
| `hwpx_read` | HWPX 본문 읽기 |
| `hwpx_convert_hwp` | `.hwp` → `.hwpx` (Windows+한글) |
| `hwpx_build` | **HWPX + PDF 생성**(자동 점검·보정) |
| `hwpx_preview` | PDF 한 쪽을 이미지로 확인 |
| `hwpx_photos` / `hwpx_photo_sheet` | 사진 목록 / 번호 붙은 한눈에 보기 이미지 |

MCP 서버는 외부 패키지 없이 표준 라이브러리만으로 구현돼(줄 단위 JSON-RPC 2.0) 설치 충돌이 없습니다.

## MCP 없이 쓰기

- 셸 명령을 실행할 수 있는 AI(Claude Code, Codex, Gemini CLI 등)는 저장소의 `AGENTS.md` 만으로 동작합니다(`hwpx-new instructions` 로도 출력).
- 명령을 실행할 수 없는 웹 채팅은 `hwpx-new prompt 서식.hwpx "요청"` 으로 만든 프롬프트를 붙여 넣으세요.

---

<p align="center"><b>리치쌤</b> · <a href="https://joo.is/AI%EB%A6%AC%EC%B9%98%EC%8C%A4">https://joo.is/AI리치쌤</a></p>
