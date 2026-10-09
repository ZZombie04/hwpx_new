# -*- coding: utf-8 -*-
"""hwpx-new report — 장편 보고서(연구학교 결과보고서·연구보고서·논문형 보고서) 명령.

  hwpx-new report init 내보고서              예시 원고(report.txt)·자료(CSV)·사진을 새 폴더에 복사(바로 빌드됨)
  hwpx-new report 내보고서/report.txt -o 결과  원고 → HWPX + PDF(차례 쪽수·표 쪽 넘김을 PDF 로 확인하며 맞춤)
  hwpx-new report check 원고 [--pdf 결과.pdf]  인용·참조·토큰·요일·쪽수 점검
  hwpx-new report guide                      원고 문법(REPORT.md)
  hwpx-new report prompt "요청" [--data 자료.csv]  채팅형 AI(웹)에 붙여 넣을 프롬프트
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_DIR = os.path.join(HERE, 'data', 'report_example')
GUIDE = os.path.join(HERE, 'REPORT.md')


def guide_text():
    return open(GUIDE, encoding='utf-8').read()


def example_text():
    return open(os.path.join(EXAMPLE_DIR, 'report.txt'), encoding='utf-8').read()


def init_example(dest, force=False):
    """예시 원고 폴더를 dest 로 복사한다. 이미 report.txt 가 있으면 덮어쓰지 않는다(force 제외). 반환: 복사한 파일 목록."""
    os.makedirs(dest, exist_ok=True)
    if os.path.exists(os.path.join(dest, 'report.txt')) and not force:
        raise FileExistsError(f'이미 원고가 있습니다: {os.path.join(dest, "report.txt")} (덮어쓰려면 --force)')
    done = []
    for root, _dirs, files in os.walk(EXAMPLE_DIR):
        rel = os.path.relpath(root, EXAMPLE_DIR)
        for f in files:
            if f.startswith(('_', '.')) or f.endswith('.pyc'):
                continue
            src = os.path.join(root, f)
            dst_dir = os.path.join(dest, rel) if rel != '.' else dest
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, f)
            if os.path.exists(dst) and not force and f != 'report.txt':
                continue
            shutil.copyfile(src, dst)
            done.append(os.path.relpath(dst, dest))
    return sorted(done)


def _data_preview(path, rows=3):
    from .stats import read_table
    head, body = read_table(path)
    lines = [f'### {os.path.basename(path)} ({len(body)}행, 열 {len(head)}개)', '| ' + ' | '.join(head) + ' |']
    for r in body[:rows]:
        lines.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(lines)


PROMPT = """너는 한국 학교·교육청 보고서(연구학교 결과보고서·연구보고서·사업 결과보고서) 작성 전문가다.
아래 [원고 문법]을 지켜 **report.txt 원고 하나만** 출력하라. 글꼴·크기·표 테두리·번호·차례 쪽수는 도구(hwpx-new)가 정하므로
너는 **글과 표시(@…)만** 쓴다. 설명·인사말 없이 원고만 ```text … ``` 안에 출력한다.

꼭 지킬 것
1. 맨 위 --- … --- 설정(title, kicker, info, date, org, theme, page_limit)부터 쓰고, @front(연구 요약·일러두기) → @body(장 Ⅰ~Ⅵ, 참고문헌) → @appendix 순서.
2. **숫자를 지어내지 않는다.** 통계 수치(평균·t·p·d·α·κ·r·비율)는 직접 쓰지 말고 `@stats …` 계산 명령을 쓰고 본문에서는 `{{접두.이름}}` 토큰으로 쓴다
   (예: `@stats paired 자료.csv --pre 사전 --post 사후 --prefix ref` → `{{ref.m0}}`, `{{ref.t}}`, `{{ref.p}}`, `{{ref.d}}`).
   자료 파일의 열 이름은 [자료]에 있는 그대로 쓴다. 자료가 없으면 숫자 자리를 `○○` 로 비우고 마지막에 `// 채울 값:` 주석으로 목록을 남긴다.
3. 연구 문제는 질문 3~4개, 결과 장의 절과 1:1. 결과 문단은 주장 → 근거(n, M, SD, t, p, 효과 크기) → 해석. 기대와 다른 결과·한계도 쓴다.
4. '입증·획기적·완벽' 같은 큰 말 금지. 검정 결과 없이 '유의' 금지.
5. 인용 `(저자, 연도)` 는 참고문헌(@r)에 반드시 있어야 하고, **실제로 있는 문헌만** 쓴다. 확인할 수 없으면 인용하지 않는다.
6. 표·그림은 본문에서 `{표:키}`·`{그림:키}` 처럼 한 번 이상 가리킨다(번호는 도구가 매김). 도표는 `@chart` 로 자료만 쓴다(그림을 그리지 않는다).
7. 날짜에 요일을 쓰면 실제 요일과 맞아야 한다. 학생 실명·얼굴은 쓰지 않는다. 학부모는 '학부모님'으로 쓴다.
8. 사용자가 주지 않은 사실(행사명·횟수·인원)은 지어내지 말고 `○○` 로 두거나, 예시 수치라면 표지 note 와 일러두기에 '가상 자료'라고 밝힌다.

[요청]
<<REQUEST>>

[자료]
<<DATA>>

[원고 문법]
<<GUIDE>>
<<EXAMPLE>>"""


def chat_prompt(request, data_files=(), with_example=True):
    data = '\n\n'.join(_data_preview(p) for p in data_files) if data_files else '(자료 파일 없음 — 수치는 ○○ 로 비운다)'
    ex = ''
    if with_example:
        ex = ('\n[완성 예시 — 이 구성과 표시 쓰는 법을 따라 하되, 내용은 요청에 맞게 새로 쓴다]\n```text\n'
              + example_text() + '```\n')
    req = request or '(여기에 만들 보고서를 적으세요: 학교명, 연구 주제, 기간, 대상, 운영 내용, 자료 파일 설명)'
    return (PROMPT.replace('<<REQUEST>>', req).replace('<<DATA>>', data)
            .replace('<<GUIDE>>', guide_text()).replace('<<EXAMPLE>>', ex))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__.strip())
        return 0
    actions = ('init', 'check', 'guide', 'prompt', 'build', 'example')
    action = argv[0] if argv and argv[0] in actions else 'build'
    if argv and argv[0] in actions:
        argv = argv[1:]
    ap = argparse.ArgumentParser(prog=f'hwpx-new report {action}'.strip())
    if action in ('init', 'example'):
        ap.add_argument('folder', nargs='?', default='내보고서')
        ap.add_argument('--force', action='store_true', help='이미 있는 원고를 덮어씀')
        a = ap.parse_args(argv)
        files = init_example(a.folder, a.force)
        print(f'예시 원고를 만들었습니다: {os.path.abspath(a.folder)} ({len(files)}개 파일)')
        print(f'  다음: hwpx-new report {os.path.join(a.folder, "report.txt")} -o {os.path.join(a.folder, "결과")}')
        print('  원고 문법: hwpx-new report guide')
        return 0
    if action == 'guide':
        print(guide_text())
        return 0
    if action == 'prompt':
        ap.add_argument('request', nargs='*')
        ap.add_argument('--data', action='append', default=[], help='자료 CSV·XLSX(열 이름을 AI 에게 알려 줌, 여러 번 가능)')
        ap.add_argument('--no-example', action='store_true', help='완성 예시 원고를 빼고 짧게')
        ap.add_argument('-o', '--out', help='프롬프트를 파일로 저장')
        a = ap.parse_args(argv)
        text = chat_prompt(' '.join(a.request), a.data, not a.no_example)
        if a.out:
            open(a.out, 'w', encoding='utf-8').write(text)
            print(f'{a.out} ({len(text):,}자) — 채팅형 AI 에 붙여 넣고, 받은 원고를 report.txt 로 저장한 뒤 hwpx-new report report.txt -o 결과')
        else:
            print(text)
        return 0
    if action == 'check':
        from .report_check import main as check_main
        return check_main(argv)
    ap.add_argument('manuscript', help='원고(report.txt) 또는 원고 폴더')
    ap.add_argument('-o', '--out', default=None, help='결과 폴더(기본: 원고 폴더/결과)')
    ap.add_argument('--name', help='파일 이름(기본: 제목)')
    ap.add_argument('--engine', choices=['hancom', 'libreoffice', 'html'])
    ap.add_argument('--passes', type=int, default=12, help='쪽 맞춤 최대 반복(기본 12)')
    ap.add_argument('--strict', action='store_true', help='점검 오류가 있으면 종료 코드 1')
    a = ap.parse_args(argv)
    from .report import build_report, summarize
    src = a.manuscript
    out = a.out or os.path.join(src if os.path.isdir(src) else os.path.dirname(os.path.abspath(src)), '결과')
    res = build_report(src, out, name=a.name, engine=a.engine, max_passes=a.passes,
                       progress=lambda k, n, m: print(f'  {m}', flush=True))
    print(summarize(res))
    errs = sum(1 for x in res.get('issues') or [] if x[0] == '오류')
    return 1 if (a.strict and errs) else 0


if __name__ == '__main__':
    sys.exit(main())
