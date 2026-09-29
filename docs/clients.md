# AI 프로그램별 연결 방법

먼저 `pip install -e .`(또는 `install.bat`)로 설치한 뒤 `hwpx-new mcp-config` 를 실행하면
**내 컴퓨터의 Python 경로가 들어간 설정**이 그대로 출력됩니다. 아래는 그 결과를 어디에 붙이는지입니다.

공통 JSON:

```json
{
  "mcpServers": {
    "hwpx_new": {
      "command": "python",
      "args": ["-m", "hwpx_new.mcp_server"]
    }
  }
}
```

> `python` 이 여러 개 설치되어 있으면 `hwpx-new mcp-config` 가 알려 주는 **전체 경로**를 `command` 에 쓰세요.

| 프로그램 | 붙이는 곳 |
|---|---|
| **Claude Code** | 터미널에서 `claude mcp add hwpx_new -- python -m hwpx_new.mcp_server` |
| **Claude Desktop** | 설정 → 개발자 → 구성 편집(`claude_desktop_config.json`)에 공통 JSON |
| **Cursor** | 프로젝트 `.cursor/mcp.json` 또는 사용자 `~/.cursor/mcp.json` 에 공통 JSON |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` 에 공통 JSON |
| **Antigravity** | MCP 서버 관리 → 설정 파일에 공통 JSON |
| **Codex CLI** | `~/.codex/config.toml` 에 아래 추가 |
| **Gemini CLI** | `~/.gemini/settings.json` 의 `mcpServers` 에 공통 JSON |
| **VS Code (Copilot)** | `.vscode/mcp.json` 에 `{"servers": {"hwpx_new": {"command": "python", "args": ["-m","hwpx_new.mcp_server"]}}}` |

Codex `config.toml`:

```toml
[mcp_servers.hwpx_new]
command = "python"
args = ["-m", "hwpx_new.mcp_server"]
```

## MCP 도구 목록

| 도구 | 역할 |
|---|---|
| `hwpx_start_here` | 사용 순서와 규칙 안내(AI 가 가장 먼저 호출) |
| `hwpx_doctor` | PDF 변환 엔진 점검 |
| `hwpx_format_guide` | 내용 작성 문법 |
| `hwpx_analyze` | 서식 분석 + 뼈대 초안 |
| `hwpx_read` | HWPX 본문 읽기 |
| `hwpx_convert_hwp` | `.hwp` → `.hwpx` (Windows+한글) |
| `hwpx_build` | **HWPX + PDF 생성**(자동 점검·보정) |
| `hwpx_preview` | PDF 한 쪽을 이미지로 확인 |

## MCP 없이 쓰기

MCP 를 지원하지 않는 AI 도 셸 명령을 실행할 수 있으면 저장소의 `AGENTS.md` 만으로 동작합니다.
명령을 실행할 수 없는 웹 채팅은 `hwpx-new prompt` 로 만든 프롬프트를 붙여 넣으세요(README 참고).

## Claude 스킬

`skill/hwpx-new/` 폴더를 통째로 `~/.claude/skills/hwpx-new/` 로 복사합니다.

---

<p align="center"><b>리치쌤</b> · <a href="https://joo.is/AI%EB%A6%AC%EC%B9%98%EC%8C%A4">https://joo.is/AI리치쌤</a></p>
