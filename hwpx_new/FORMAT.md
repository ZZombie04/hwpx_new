# 내용 작성 형식 (Markdown 확장)

서식(HWPX)의 **모양은 자동으로 복제**됩니다. 여러분(AI)은 아래 문법으로 **글과 구조만** 쓰면 됩니다.
빈 줄·간격·번호 모양·표 테두리·글자 색은 서식에서 배운 대로 적용되므로 신경 쓰지 않습니다.

**가장 안전한 방법**: `hwpx-new analyze 서식.hwpx` 가 돌려주는 **뼈대 Markdown** 을 복사해 글만 바꾸고 구조를 재구성한다.
뼈대는 서식을 그대로 다시 만들어 내므로(서식 재현도 점검 `hwpx-new selfcheck`), 뼈대에 있는 표시(`{B2}`, `:::cover`, `@clone`, `@like`, json 블록)를 그대로 두면 모양이 유지된다.

| 쓰는 법 | 결과 |
|---|---|
| `# 문서 제목` | 표지/제목 (표지가 한두 칸인 서식) |
| `:::cover` … `:::` | **표지 글 칸**: 줄 하나가 칸 하나. 칸 수·순서는 그대로, 글만 바꾼다 |
| `@subtitle 작성 부서` | 제목 아래 부서명 칸(표지에 오른쪽/가운데 정렬 짧은 칸이 있을 때) |
| `## Ⅰ. 소제목` | 소제목(번호는 글로 직접: `Ⅰ.` `1.` `가.`). 서식의 번호 칸·띠 모양은 자동 |
| `- 내용` / `  - 내용`(2칸) | 글머리 문단 1단계 / 2단계… (기호는 서식에서 배운 것: ○ ㅇ - □ …) |
| `1. 내용` / `가. 내용` | 번호 문단 |
| 그냥 한 줄 | 본문 문단 |
| `**굵게**` | 문단 안 굵은 낱말(서식의 굵은 글자 모양으로) |
| `{B2} 내용`, `## {H2} 제목`, `:::box {X1} 제목` | **서식 종류 지정**: 같은 역할에 모양이 여러 가지일 때 어느 모양을 쓸지 고름. 종류 이름·모양은 `analyze` 의 "서식 종류" 목록 |
| `<!-- class: T3 -->` (표 바로 위) | 표의 모양(머리 색·테두리) 종류 지정 |
| GFM 표 | 표. 첫 줄이 머리글. 칸 안 줄바꿈 `<br>`. 열 너비·정렬은 서식의 같은 표에서 배움(지정하려면 `<!-- widths: 1,3,2 -->`, 구분줄 `:-:` 가운데 / `:--` 왼쪽 / `--:` 오른쪽) |
| `:::box 제목` … `:::` | 강조 박스(줄마다 한 문단). 제목 줄은 박스 제목 모양 |
| `<!-- pagebreak -->` | 다음 블록을 새 쪽에서 시작 |
| `@end` | 공문 끝 표시 "끝." |
| `@like 34 \| 새 글` | 34번 블록의 모양을 그대로 빌려 글만 교체. 바꾸지 않은 낱말의 글자 모양(색·굵기)은 유지, 새 낱말은 이웃 글자 모양을 따름 |
| `@clone 12` / `@clone 12-15` | 서식의 12번(~15번) 블록을 **그대로 복제**(사진·도면·서명란 등) |
| `![캡션](사진경로)` (한 줄에 하나) | 단독 사진 + 가운데 캡션 |
| 한 줄에 `![](a.jpg) ![](b.jpg)` 여러 개 | 사진 격자(표) |
| `:::photos columns=3 title="제목" width_mm=50 max_height_mm=60` … `:::` | 사진 대지(표 안에 사진 격자 + 캡션 줄) |
| 표 셀 안의 `![설명](사진경로)` | 셀 안에 사진(설명은 사진 아래 글) |

## JSON 블록 (병합 셀·양식 복제·세밀한 제어)

Markdown 안에 ` ```json … ``` ` 로 블록 하나(또는 목록)를 그대로 쓸 수 있고, 문서 전체를 `{"blocks": [ ... ]}` JSON 으로 쓸 수도 있다.

```json
{"type": "table",
 "header": [[{"text": "기수", "rowspan": 2}, {"text": "강사", "colspan": 2}],
            [{"text": "주"}, {"text": "보조"}]],
 "rows": [["1기", "홍길동", "김철수"]],
 "widths": [1, 2, 2], "align": ["c", "l", "l"], "class": "T3"}
```

| type | 주요 키 |
|---|---|
| `title` | `text`, `fields`(표지 글 칸을 순서대로 지정) |
| `heading` / `paragraph` / `numbered` / `bullet` | `text`, `level`(글머리), `class`, `page_break` |
| `box` | `title`, `lines`, `class` |
| `table` | `header`(문자열 목록 = 1줄, 목록의 목록 = 여러 줄), `rows`, `widths`, `align`, `class`, `proto`(서식 블록 번호), `min_row`, `floating` |
| `clone` | `from`, `to`, `section`, `text`(한 문단 교체), `paras`(글이 있는 문단을 차례로 교체 — 항목을 `{"like":k,"text":…}` 로 쓰면 k번 문단 모양의 새 문단을 끼워 넣음), `texts`(글 덩어리 단위 교체), `replace`(문구 치환), `scale_height`(꽉 찬 양식 표의 높이 비율 축소, 예 0.9) |
| `table` 추가 키 | `inline: true`(서식의 떠 있는 표를 글자처럼 취급 — 뒤 문단이 표 아래로 밀림) |
| `like` | `clone` 과 같음(뜻을 분명히 하는 이름) |
| `image` / `gallery` | `path`·`caption`·`width_mm` / `images`·`columns`·`title` |
| `blank`, `end` | 빈 줄, "끝." |

- 셀은 문자열 | `{"text":..., "colspan":n, "rowspan":n, "align":"c|l|r"}`.
- `clone` 의 `replace`: 복제한 블록 안 문구 치환(글자 모양 유지). `probe`/`qa`: 조판 점검용 힌트(소제목이 표와 함께 있도록 등).
- 복제 요소에는 빈 줄이 자동으로 붙지 않으므로 간격이 필요하면 `{"type":"clone","from":<빈 줄 블록>}`.

## 사진

- 경로는 내용 파일이 있는 폴더 기준 상대 경로 또는 절대 경로. `hwpx-new photos 폴더` 로 사진을 미리 살펴본다.
- 자동 처리: EXIF 회전 보정, 긴 변 1600px 로 축소, HEIC/WEBP 등은 JPG/PNG 로 변환, 표시 크기는 칸 폭에 맞춰 비율 유지.
- 셀 안 사진의 최대 높이는 기본 70mm(`max_height_mm`), 사진 대지는 60mm.

## 좋은 결과를 위한 요령

1. **뼈대를 따른다**: 소제목·표 구조를 기준으로 새 목적에 맞게 다시 쓴다. 같은 모양의 줄을 더 쓸 때는 뼈대의 그 줄 표시(`{B2}` 등)를 복사한다.
2. 표의 열 수가 서식과 같으면 칸 모양·열 너비·테두리를 같은 자리에서 그대로 가져오고, 다르면 서식의 표 설계에서 자동 배분한다(7열 이상은 피한다).
3. 문장 어미·문체는 서식 원문과 통일한다(공문서는 개조식 `~함.` `~임.`, 안내문은 `~합니다.`).
4. 표지·머리말 성격의 칸(기관명·날짜·대회명)에 서식 원문의 글이 남지 않게 모두 바꾼다.
5. 사용자가 주지 않은 사실(숫자·인명·날짜)을 지어 넣었다면 **반드시 최종 답변에 목록으로 알린다.**

---

# 명세(JSON) 형식 — compose · gongmun · patch

모양은 도구가 정하고, AI 는 글과 구조만 JSON 으로 쓴다. 예시 파일: 저장소 `examples/compose_spec.json`, `examples/gongmun_spec.json`, `examples/patch_ops.json`.
글 안에서 `**굵게**`, `^^강조(진한 빨강)^^` 를 쓸 수 있다. 상대 경로는 명세 파일이 있는 폴더 기준.

## 표(compose·gongmun·patch 공통)

`{"table": {"rows": [[칸, …], …], "label_col": true, "head": 1, "widths": [9500, 38690], "aligns": ["c", "l"], "size": "s", "split": false}}`
- 칸 = 글 또는 `{"t": "글", "cs": 2, "rs": 3, "a": "l", "b": true, "fill": "#F2F2F2", "accent": true}`. 칸 안 줄바꿈은 `\n`, 줄 앞 `- `·`※ ` 는 내어쓰기.
- 그림 칸 `{"img": "그림.png", "w_mm": 25}`, QR 칸 `{"qr": "https://…", "caption": "QR 바로가기", "rs": 3, "size_mm": 21}`.
- `label_col: true` 이면 첫 열이 항목 열(연회색·굵게)이고 머리행 없음(`head` 0)이 기본. 너비를 안 주면 자동.

## 조판 명세(compose) — `hwpx-new compose 명세.json -o 결과.hwpx --check`

`{"template", "heading_block"(대제목 표 블록 번호, 선택), "cover": {"from", "to", "replace", "wrap"}(선택), "title", "blocks": [...]}`
블록: `{"h1": "Ⅰ 제목"}`(`"page": true` 면 새 쪽) · `{"h2"}` · `{"b1"}` · `{"b1h"}`(굵은 묶음 제목) · `{"b2"}` · `{"b3"}` ·
`{"note": "…", "level": 1|2}` · `{"p": "…", "style": "body"}` · `{"table": …}` · `{"box": {"title", "lines": ["❍ …", "- …"]}}` ·
`{"image": {"path", "width_mm", "max_h_mm", "caption"}}` · `{"page": true}` · `{"blank": true}` · `{"clone": {"from", "to", "replace", "recolor"}}`

## 공문 명세(gongmun) — `hwpx-new gongmun 명세.json -o 결과.hwpx --check`

| 키 | 뜻 |
|---|---|
| `template` | 기관 공문 서식(머리 표 '수신'·'제목' 칸, 결재란 '시행'·'협조자'가 든 HWPX) |
| `receiver`, `title` | 머리 표의 수신 칸(예: "수신자 참조", "내부결재"), 제목 칸 |
| `body` | 줄(문자열) 또는 `{"table": …}` / `{"page": true}`. 줄 앞 번호로 단계: `1.` → `가.` → `1)` → `가)`, `※` 참고 |
| `attachments` | 붙임 목록(없으면 마지막 줄 뒤에 `끝.`). "○○ 계획" → "붙임  ○○ 계획 1부.  끝." |
| `sender` | 발신 명의(시행문만, 예: "○○교육지원청교육장") |
| `receivers` | 수신자 참조일 때 수신자 줄(목록) |
| `approval` | 결재란 칸 바꾸기 `{"시행": "○○과-○○○○(2026. 10. ○○.)"}` 또는 `{"replace": {"옛": "새"}}` |
| `head_replace`, `font`, `size` | (선택) 머리 표 글 치환, 본문 글꼴·크기(기본: 서식 본문과 같게) |

## 고치기(patch) — `hwpx-new patch 원본.hwpx ops.json -o 결과.hwpx [--style gongmun] --check`

`[{"op": "replace_text", "find", "to", "count"|"all"}, {"op": "replace_block", "find", "blocks"}, {"op": "insert_after"|"insert_before", "find", "blocks"},
{"op": "delete_block", "find"}, {"op": "page_break", "find", "on": true|false}]`
- `find`: 그 블록에만 있는 글(빈칸 무시). 정확히 한 블록이어야 한다(아니면 후보와 함께 멈춤). 같은 글이 여러 블록이면 `"nth": 2`.
- `blocks`: 조판 명세 블록과 같은 문법(공문이면 `--style gongmun` 에 "가. …" 줄과 `{"table"}`).
- 나머지 블록은 하나도 바꾸지 않고 그대로 복제한다(사용자가 맞춘 자간·빈 줄·들여쓰기·글자색 유지).
