# hwpx_new

**한글(HWPX) 서식 파일 하나만 주면, AI 가 그 서식이 어떤 문서인지 스스로 파악하고 — 원하는 목적에 맞게 새로 써서 — 같은 서식의 `HWPX` 와 `PDF` 두 파일로 만들어 줍니다.**

> "이 계획서를 결과보고서로 바꿔줘" · "작년 안내문을 올해로 고쳐줘" · "이 양식으로 새 보고서 만들어줘"

Claude · ChatGPT(Codex) · Gemini · Grok · Cursor · Antigravity 등 **어떤 AI 에서도** 같은 결과가 나오도록 만든 스킬 + MCP + 명령줄 도구입니다.

| 서식(계획서) | → | 결과(결과보고서) |
|:-:|:-:|:-:|
| ![서식](docs/img/template_p1.png) | | ![결과](docs/img/result_p1.png) |

표지 띠, 소제목 바, 표 색·테두리, 강조 박스, ● 글머리, 쪽 번호까지 **원본 서식 그대로** 복제됩니다.

---

## 한눈에 보는 작동 방식

```
서식.hwpx ─▶ ① 분석 ─▶ ② 뼈대 파악 ─▶ ③ AI 가 내용 작성 ─▶ ④ 서식 복제 조립 ─▶ ⑤ PDF 변환
             (표지·소제목·표·박스·         (계획서? 공문?      (Markdown 으로         (원본 서식 그대로     (한글 → 없으면
              글머리 자동 분류)             어떤 절 구성?)      내용만 씀)             HWPX 생성)           LibreOffice → 내장)
                                                                                          │
                              HWPX + PDF ◀─ ⑧ 미리보기 확인 ◀─ ⑦ 자동 보정(쪽 나눔·간격) ◀─ ⑥ 조판 자동 점검
```

- **⑥ 조판 자동 점검**: 빈 쪽, 소제목만 쪽 끝에 홀로 남음, 표가 쪽 사이에서 잘림, 마지막 쪽에 몇 줄만 남음을 PDF 에서 찾아냅니다.
- **⑦ 자동 보정**: 쪽 나눔을 넣고 간격을 줄여 스스로 고친 뒤 다시 확인합니다(최대 6회).
- 날짜와 요일이 안 맞으면(예: `2026. 9. 16.(화)`) 경고합니다.

## 설치 (5분)

1. **Python 3.9 이상** 설치 (Windows 는 설치 화면에서 *Add python.exe to PATH* 체크)
2. 이 저장소를 내려받아 설치 프로그램 실행
   - Windows: `install.bat` 더블클릭
   - macOS/Linux: `bash install.sh`
   - 또는 한 줄: `pip install git+https://github.com/ZZombie04/hwpx_new.git`
3. 설치 확인
   ```bash
   hwpx-new doctor
   ```
   > **한글(Hancom Office)이 설치된 Windows** 에서는 실제 한글로 PDF 를 만들어 쪽 배치가 가장 정확합니다.
   > 한글이 없으면 Chrome/Edge 기반 내장 렌더러가 **근사 PDF** 를 만듭니다(HWPX 자체는 동일).

## AI 에 연결하기 (가장 쉬운 방법부터)

### A. 명령줄 AI (Claude Code · Codex · Gemini CLI · Grok · Antigravity …)

이 폴더를 열고 그냥 말하면 됩니다. 저장소 루트의 `AGENTS.md`(= `CLAUDE.md`, `GEMINI.md`)에 **작업 절차 전체**가 들어 있어
AI 가 스스로 읽고 분석 → 작성 → 변환 → 확인 → 보정까지 수행합니다.

```
서식.hwpx 를 분석해서 결과보고서로 만들어줘. 연수는 9/16, 9/22 두 번 했고 각각 11명, 13명 이수했어.
```

### B. MCP (Claude Desktop · Claude Code · Cursor · Windsurf · Codex · Gemini …)

```bash
hwpx-new mcp-config        # 내 컴퓨터에 맞는 설정을 프로그램별로 출력합니다
```

출력된 JSON 을 각 프로그램의 MCP 설정에 붙여 넣으면 `hwpx_analyze`, `hwpx_build`, `hwpx_preview` 등 도구가 생깁니다.
Claude Code 는 한 줄이면 됩니다.

```bash
claude mcp add hwpx_new -- python -m hwpx_new.mcp_server
```

자세한 프로그램별 설정은 [docs/clients.md](docs/clients.md).

### C. Claude 스킬로 설치

`skill/hwpx-new` 폴더를 `~/.claude/skills/` 에 복사하면 "이 서식으로 ~ 만들어줘" 같은 요청에서 자동으로 켜집니다.

### D. 도구 연결이 없는 채팅 AI (웹 ChatGPT · Gemini · Grok 등)

```bash
hwpx-new prompt 서식.hwpx "이 계획서를 결과보고서로 바꿔줘. 이수 24명"   # ← 출력 전체를 AI 채팅창에 붙여넣기
# AI 가 준 Markdown 을 content.md 로 저장한 뒤
hwpx-new build 서식.hwpx content.md -o 결과
```

## 이렇게 말하세요 (예시)

| 하고 싶은 일 | AI 에게 |
|---|---|
| 계획서 → 결과보고서 | "`계획서.hwpx` 를 결과보고서로 만들어줘. 참석 24명, 만족도는 매우 좋았어" |
| 작년 문서 → 올해 | "작년 `안내문.hwpx` 를 올해(2026년 10월 14일 수요일) 행사로 바꿔줘" |
| 같은 양식으로 새 문서 | "이 `양식.hwpx` 로 ○○ 사업 운영 계획서 만들어줘. 자료는 아래와 같아…" |
| 사진·도면이 많은 기존 문서를 우리 기관용으로 | "`도교육청 요강.hwpx` 와 `도 계획.hwp` 를 읽고, 우리 지역 조건(참가 대상·신청 방법·시상)을 넣어 운영 계획서와 신청서 엑셀을 만들어줘" (원본 사진·표·양식은 그대로 복제) |
| 옛 `.hwp` 파일 | "`서식.hwp` 로 …" (Windows+한글이면 자동 변환) |

AI 는 마지막에 **HWPX 경로, PDF 경로, (지어낸 내용이 있다면) 그 목록**을 알려 줍니다.
사용자가 주지 않은 숫자·이름을 임의로 만들지 않는다는 규칙이 지침에 들어 있습니다.

## 사진도 알아서 넣어 줍니다

```
서식(계획서).hwpx 로 결과보고서 만들어줘. 사진은 사진/ 폴더에 있어. 1기는 9/16, 11명 이수.
```

1. `hwpx-new photos 사진/` — 촬영 시각 순 목록과 **번호 붙은 한눈에 보기 이미지**를 만듭니다. AI 가 이 이미지를 보고 각 사진이 무엇인지 파악합니다.
2. AI 가 활동 장면은 **사진 대지**(표 안의 사진 격자 + 캡션), 단체 사진은 **단독 사진**, 설문지·자료는 **표 셀 안**에 넣도록 배치를 정합니다.
3. 사진은 자동으로 **회전 보정 · 축소 · 형식 변환(HEIC 등)** 후 HWPX 안에 들어가고, PDF 로도 확인합니다.

```markdown
:::photos columns=3 title="1기 실습 장면"
![준비운동 실습](사진/01.jpg)
![스피드 레더](사진/02.jpg)
![허들 릴레이](사진/03.jpg)
:::

![연수 참여 교원 단체 사진](사진/05.jpg)

| 사진 | 설명 |
|:-:|:--|
| ![](사진/04.jpg) | 만족도 설문 작성 모습 |
```

![사진이 들어간 결과 페이지](docs/img/result_photos.png)

예시: [examples/sample_content_photos.md](examples/sample_content_photos.md) → [결과 PDF](examples/output/샘플_결과보고서_사진포함.pdf)

## 명령어 모음

| 명령 | 설명 |
|---|---|
| `hwpx-new doctor` | PDF 변환 엔진 상태 점검 |
| `hwpx-new analyze 서식.hwpx` | 서식 구조 분석(표지·소제목·표·박스·글머리) |
| `hwpx-new scaffold 서식.hwpx` | 서식 뼈대 그대로의 Markdown 초안 |
| `hwpx-new photos 사진폴더` | 사진 목록 + 번호 붙은 한눈에 보기 이미지 |
| `hwpx-new read 문서.hwpx` | HWPX 본문을 Markdown 으로 읽기 |
| `hwpx-new build 서식.hwpx content.md -o 결과폴더` | **HWPX + PDF + 미리보기 PNG** 생성(자동 점검·보정 포함) |
| `hwpx-new preview 결과.pdf --page 2` | PDF 한 쪽을 PNG 로 |
| `hwpx-new convert 옛서식.hwp` | `.hwp` → `.hwpx` (Windows + 한글) |
| `hwpx-new prompt 서식.hwpx "요청"` | 채팅 AI 용 완성 프롬프트 |
| `hwpx-new format` | 내용 작성 문법 |
| `hwpx-new mcp-config` | MCP 설정 출력 |

## 내용 작성 문법 (핵심)

```markdown
# 문서 제목
@subtitle 작성 부서
## Ⅰ. 소제목
- 글머리 문단
  - 하위 단계
:::box 강조 박스 제목
박스 안 줄
:::
<!-- widths: 1.3, 3.5 -->
| 항목 | 내용 |
|:-:|:-:|
| 연수명 | 2026 ○○ 연수 |
<!-- pagebreak -->
@end
```

빈 줄·간격·번호 모양·표 테두리는 **서식에서 배워서 자동 적용**되므로 적지 않습니다.
병합 셀이 있는 표, 기안문의 여러 칸 제목 등은 JSON 블록으로 쓸 수 있습니다 → [docs/content-format.md](docs/content-format.md)

## 어떻게 서식을 알아내나요

HWPX 는 ZIP 안의 XML 입니다. `hwpx_new` 는 문서의 각 블록을 살펴 **역할**을 붙입니다.

| 역할 | 판정 근거 |
|---|---|
| 표지/제목 | 앞쪽 블록 중 번호 머리말이 아닌 큰 글씨(표 포함) |
| 부제 | 제목 아래 짧은 오른쪽·가운데 정렬 문단 |
| 소제목 | `Ⅰ.` `1.` `가.` 로 시작하는 짧은 1열 표(바 장식) 또는 큰 굵은 문단 |
| 표 | 머리글 배경색이 있는 격자 → 머리/본문/마지막 행, 첫/중간/끝 열별 테두리·글꼴을 학습 |
| 박스 | 배경색 1×1 표 → 제목 줄과 본문 줄 서식 분리 |
| 글머리/번호 문단 | ●○-, `1.` `가.` `1)` 등 → 단계별 들여쓰기·기호 학습 |
| 빈 줄 | 블록 사이 간격 규칙(표 뒤, 소제목 뒤 …)을 학습해 자동 삽입 |

이렇게 배운 서식 요소를 **복제해 글만 바꾸므로** 글꼴·색·여백이 원본과 같습니다. 자세한 내용은 [docs/how-it-works.md](docs/how-it-works.md).

## 자주 묻는 질문

**PDF 가 한글에서 연 것과 조금 달라요.** 한글이 없는 환경에서는 내장 렌더러가 만든 근사 PDF 입니다. 한글이 설치된 Windows 에서는 한글 자신이 PDF 로 저장합니다.

**한글 변환이 멈추거나 오래 걸려요.** 한글은 외부 프로그램이 파일을 열려 하면 **"파일 접근 허용" 보안 승인 창**을 띄웁니다(화면 뒤에 숨어 있을 수 있음). 그 창에서 [허용]을 누르면 진행됩니다. 75초 안에 응답이 없으면 자동으로 다음 엔진(LibreOffice → 내장 렌더러)으로 넘어가 PDF 는 반드시 만들어지고, 이 도구가 띄운 한글 프로세스만 정리합니다(사용자가 열어 둔 한글 문서는 건드리지 않습니다). 승인 창이 매번 뜨는 것이 불편하면 한글 자동화 보안 모듈(FilePathChecker) 등록을 직접 검토하세요 — 보안 설정이라 이 도구가 대신 바꾸지 않습니다.

**`.hwp` 파일은요?** 옛 형식이라 직접 읽지 않습니다. `hwpx-new convert` 또는 한글에서 *다른 이름으로 저장 → HWPX*.

**서식에 원래 있던 그림(로고 등)은요?** 표지 장식처럼 표 안에 든 그림은 그대로 복제됩니다. 새 사진은 위의 `![캡션](경로)` 문법으로 넣습니다.

**표에 열이 너무 많으면?** 7열 이상이면 경고합니다. 열을 줄이거나 표를 나눠 쓰세요.

## 한계

- 서식의 첫 번째 구역(섹션)만 사용합니다.
- 각주·수식·도형은 복제하지 않습니다(표지 띠 같은 표 장식은 그대로 유지).
- 기안문처럼 특수한 구조는 `clone` 블록과 `fields` 로 칸을 채워야 할 수 있습니다.

## 개발 / 테스트

```bash
pip install -e .
python tests/test_e2e.py      # 서식 분석 → 조립 → PDF → 점검 전 과정
python tests/test_mcp.py      # MCP 서버 왕복
```

## 라이선스

MIT — [LICENSE](LICENSE)

---

<p align="center"><b>리치쌤</b> · <a href="https://joo.is/AI%EB%A6%AC%EC%B9%98%EC%8C%A4">https://joo.is/AI리치쌤</a></p>
