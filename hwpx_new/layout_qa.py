# -*- coding: utf-8 -*-
"""조판 점검(Playwright): 한글이 만든 PDF 의 글줄을 뽑아 브라우저에서 규칙 검사 + 문제 위치 표시 스크린숏.

사용:
    hwpx-new qa 결과.pdf [-o 점검폴더] [--skip 1] [--colors "#000000,#FFFFFF,#C00000"]

검사 항목(정돈 조판 규칙)
  1. 글자색: 허용 색(검정·흰색·강조 빨강) 외의 글자
  2. 단계 정렬: 같은 기호·크기(■ 15pt, ❍ 14pt, - 13pt, ※ 12pt)의 줄머리 x 위치가 쪽마다 같은지
  3. 내어쓰기: 기호 문단의 둘째 줄이 첫 줄 글자 시작 위치에 맞는지
  4. 글꼴 통일: 같은 단계는 같은 글꼴인지
  5. 여백 넘침, 6. 글줄 겹침, 7. 쪽 끝에 홀로 남은 소제목, 8. 거의 빈 쪽

Node + Playwright 가 필요하다(환경변수 PLAYWRIGHT_MODULE 로 playwright 모듈 경로 지정 가능).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import pymupdf

MARKERS = ('■', '❍', '- ', '· ', '※')


def extract(pdf, out_dir, dpi=96):
    d = pymupdf.open(pdf)
    pages = []
    for i, pg in enumerate(d):
        lines = []
        for b in pg.get_text('rawdict')['blocks']:
            if b.get('type') != 0:
                continue
            for ln in b['lines']:
                spans = [s for s in ln['spans'] if ''.join(c['c'] for c in s['chars']).strip()]
                if not spans:
                    continue
                chars = [c for s in ln['spans'] for c in s['chars']]
                text = ''.join(c['c'] for c in chars)
                lead = len(text) - len(text.lstrip())
                chars = chars[lead:]
                text = text.strip()
                # 줄머리 기호 다음 첫 글자의 x(묶음 빈칸은 PDF 글자로 나오지 않음)
                tx = None
                if chars and chars[0]['c'] in '■❍※·-':
                    j = 1
                    while j < len(chars) and chars[j]['c'] in '  ':
                        j += 1
                    if j < len(chars):
                        tx = round(chars[j]['bbox'][0], 2)
                s0 = spans[0]
                lines.append({
                    'text': text, 'x0': round(chars[0]['bbox'][0], 2) if chars else round(s0['bbox'][0], 2),
                    'y0': round(min(s['bbox'][1] for s in spans), 2), 'x1': round(max(s['bbox'][2] for s in spans), 2),
                    'y1': round(max(s['bbox'][3] for s in spans), 2), 'tx': tx,
                    'size': round(s0['size'], 1), 'font': s0['font'],
                    'colors': sorted({'#%06X' % s['color'] for s in spans}),
                })
        img = os.path.join(out_dir, f'page_{i + 1}.png')
        pg.get_pixmap(dpi=dpi).save(img)
        # 표·박스 영역(선으로 둘러싼 사각형): 칸 안 글줄은 단계 정렬 검사에서 뺀다
        rects = []
        for dr in pg.get_drawings():
            r = dr['rect']
            if r.width > 40 and r.height > 8:
                rects.append([round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)])
        hlines = []
        for dr in pg.get_drawings():
            for it in dr['items']:
                if it[0] == 'l':
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) < 0.5 and abs(p1.x - p2.x) > 30:
                        hlines.append([round(min(p1.x, p2.x), 1), round(p1.y, 1), round(max(p1.x, p2.x), 1)])
                    elif abs(p1.x - p2.x) < 0.5 and abs(p1.y - p2.y) > 6:
                        rects.append([round(p1.x, 1) - 0.5, round(min(p1.y, p2.y), 1), round(p1.x, 1) + 0.5,
                                      round(max(p1.y, p2.y), 1)])
        pages.append({'n': i + 1, 'w': pg.rect.width, 'h': pg.rect.height, 'img': os.path.basename(img),
                      'lines': lines, 'rects': rects, 'hlines': hlines})
    return pages


HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>조판 점검</title>
<style>
body{margin:0;background:#f2f2f2;font:13px/1.5 sans-serif;color:#111}
header{padding:12px 16px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:5}
.page{position:relative;margin:16px auto;background:#fff;box-shadow:0 1px 4px #0003}
.page img{display:block;width:100%}
.hit{position:absolute;border:2px solid #e00;background:#ff000018}
.hit.warn{border-color:#f90;background:#ff990018}
.tag{position:absolute;left:0;top:-18px;background:#e00;color:#fff;font-size:11px;padding:0 4px;white-space:nowrap}
.warn .tag{background:#f90}
#sum li{margin:2px 0}
</style></head><body>
<header><b>조판 점검</b> <span id="stat"></span><ul id="sum"></ul></header>
<div id="pages"></div>
<script>
const DATA = __DATA__;
const CFG = __CFG__;
function inside(l, rects){ // 글줄 중심이 표·박스 사각형 안에 있는가
  const cx=(l.x0+l.x1)/2, cy=(l.y0+l.y1)/2;
  return rects.some(r=>cx>r[0]+1&&cx<r[2]-1&&cy>r[1]&&cy<r[3]);
}
function inTable(p, l){
  // 세로선 두 개 사이 또는 사각형 안이면 칸으로 본다
  const cy=(l.y0+l.y1)/2, cx=(l.x0+l.x1)/2;
  const v=p.rects.filter(r=>r[2]-r[0]<2 && cy>r[1]-1 && cy<r[3]+1);
  const left=v.some(r=>r[0]<=l.x0+0.5), right=v.some(r=>r[0]>=l.x1-0.5);
  if(left&&right) return true;
  const boxes=p.rects.filter(r=>r[2]-r[0]>=40);
  if(boxes.some(r=>cx>r[0]+1&&cx<r[2]-1&&cy>r[1]&&cy<r[3])) return true;
  // 위아래 가로선 사이(좌우 바깥선이 없는 표)
  const above=p.hlines.some(h=>h[1]<=l.y0+1 && h[1]>l.y0-40 && h[0]<=cx && h[2]>=cx);
  const below=p.hlines.some(h=>h[1]>=l.y1-1 && h[1]<l.y1+40 && h[0]<=cx && h[2]>=cx);
  return above&&below;
}
function marker(t){ if(/^- ?\d+ ?-$/.test(t)) return null; const m=t.match(/^(■|❍|※|·|-)/); return m?m[1]:null; }
function mode(arr){ const c={}; arr.forEach(x=>c[x]=(c[x]||0)+1); return +Object.entries(c).sort((a,b)=>b[1]-a[1])[0][0]; }
function runChecks(){
  const issues=[]; const add=(p,l,kind,msg,level='err')=>issues.push({page:p.n,kind,msg,level,box:l?[l.x0,l.y0,l.x1,l.y1]:null,text:l?l.text.slice(0,40):''});
  const pages=DATA.filter(p=>!CFG.skip.includes(p.n));
  const allow=CFG.colors.map(c=>c.toUpperCase());
  // 1 글자색
  pages.forEach(p=>p.lines.forEach(l=>{const bad=l.colors.filter(c=>!allow.includes(c)); if(bad.length) add(p,l,'색',`허용되지 않은 글자색 ${bad.join(',')}`);}));
  // 단계 줄머리 수집(표 밖 본문만)
  const groups={};
  pages.forEach(p=>p.lines.forEach((l,i)=>{ if(inTable(p,l)) return; const m=marker(l.text); if(!m) return;
    const key=m+'|'+l.size; (groups[key]=groups[key]||[]).push({p,l,i}); }));
  Object.entries(groups).forEach(([key,arr])=>{
    if(arr.length<2) return;
    const xm=mode(arr.map(a=>Math.round(a.l.x0)));
    // 2 단계 정렬
    arr.forEach(a=>{ if(Math.abs(a.l.x0-xm)>1.6) add(a.p,a.l,'정렬',`'${key.split('|')[0]}' ${key.split('|')[1]}pt 줄머리 x=${a.l.x0.toFixed(1)} (기준 ${xm})`); });
    // 4 글꼴 통일
    const fm=Object.entries(arr.reduce((c,a)=>(c[a.l.font]=(c[a.l.font]||0)+1,c),{})).sort((a,b)=>b[1]-a[1])[0][0];
    arr.forEach(a=>{ if(a.l.font!==fm) add(a.p,a.l,'글꼴',`같은 단계인데 글꼴이 다름: ${a.l.font} (기준 ${fm})`); });
    // 3 내어쓰기: 다음 줄이 기호 없는 이어지는 줄이면 첫 줄 글자 시작 위치에 맞아야 함
    arr.forEach(a=>{
      const l=a.l, nx=a.p.lines[a.i+1]; if(!nx||marker(nx.text)||inTable(a.p,nx)) return;
      if(Math.abs(nx.size-l.size)>0.2) return; const gap=nx.y0-l.y1; if(gap<-1||gap>l.size*1.2) return;
      const tx = l.tx; if(tx===null||tx===undefined){ return; }
      if(Math.abs(nx.x0-tx)>2.2) add(a.p,nx,'내어쓰기',`둘째 줄 x=${nx.x0.toFixed(1)} 이 첫 줄 글자 시작 ${tx.toFixed(1)} 에 맞지 않음`,'warn');
    });
  });
  // 5 여백 넘침, 6 겹침, 7 홀로 남은 소제목, 8 거의 빈 쪽
  pages.forEach(p=>{
    const L=p.lines;
    L.forEach(l=>{ if(l.x1>p.w-CFG.margin||l.x0<CFG.margin-6) add(p,l,'여백',`본문 영역 밖(x ${l.x0.toFixed(0)}~${l.x1.toFixed(0)})`); });
    for(let i=0;i<L.length;i++)for(let j=i+1;j<L.length;j++){const a=L[i],b=L[j];
      const ox=Math.min(a.x1,b.x1)-Math.max(a.x0,b.x0), oy=Math.min(a.y1,b.y1)-Math.max(a.y0,b.y0);
      if(ox>2&&oy>Math.min(a.y1-a.y0,b.y1-b.y0)*0.45) add(p,a,'겹침',`글줄 겹침: "${b.text.slice(0,20)}"`);}
    const body=L.filter(l=>!/^- ?\d+ ?-$/.test(l.text));
    const heads=body.filter(l=>l.text.startsWith('■')&&!inTable(p,l));
    heads.forEach(h=>{ const after=body.filter(l=>l.y0>h.y1+1); if(after.length===0||h.y1>p.h*0.86) add(p,h,'쪽끝',`소제목이 쪽 끝에 홀로 남음`); });
    if(body.length){ const top=Math.min(...body.map(l=>l.y0)), bot=Math.max(...body.map(l=>l.y1));
      if((bot-top)/(p.h-2*CFG.margin) < CFG.minFill && p.n!==DATA[DATA.length-1].n) add(p,null,'빈쪽',`쪽 내용이 ${Math.round((bot-top)/(p.h-2*CFG.margin)*100)}%만 채워짐`,'warn'); }
  });
  return issues;
}
function render(issues){
  const box=document.getElementById('pages');
  DATA.forEach(p=>{
    const d=document.createElement('div'); d.className='page'; d.id='p'+p.n; d.style.width=(p.w*CFG.scale)+'px';
    d.innerHTML=`<img src="${p.img}">`;
    issues.filter(x=>x.page===p.n&&x.box).forEach(x=>{const h=document.createElement('div'); h.className='hit '+(x.level==='warn'?'warn':'');
      const s=CFG.scale; h.style.left=(x.box[0]*s-2)+'px'; h.style.top=(x.box[1]*s-2)+'px'; h.style.width=((x.box[2]-x.box[0])*s+4)+'px'; h.style.height=((x.box[3]-x.box[1])*s+4)+'px';
      h.innerHTML=`<span class="tag">${x.kind}</span>`; d.appendChild(h);});
    box.appendChild(d);
  });
  const errs=issues.filter(x=>x.level!=='warn').length, warns=issues.length-errs;
  document.getElementById('stat').textContent=`쪽 ${DATA.length} · 오류 ${errs} · 주의 ${warns}`;
  document.getElementById('sum').innerHTML=issues.slice(0,60).map(x=>`<li>${x.page}쪽 [${x.kind}] ${x.msg} ${x.text?'— '+x.text:''}</li>`).join('');
}
window.QA = runChecks(); render(window.QA);
</script></body></html>"""

MJS = r"""
const path = require('path');
const fs = require('fs');
function loadPlaywright() {
  const cands = [process.env.PLAYWRIGHT_MODULE, 'playwright'].filter(Boolean);
  for (const c of cands) { try { return require(c); } catch (e) {} }
  throw new Error('playwright 모듈을 찾지 못했습니다(PLAYWRIGHT_MODULE 환경변수로 경로 지정).');
}
(async () => {
  const [html, outDir] = process.argv.slice(2);
  const { chromium } = loadPlaywright();
  let browser;
  try { browser = await chromium.launch(); }
  catch (e) {
    // 설치된 playwright 버전과 내려받은 브라우저 버전이 다를 때: 이미 있는 Chromium 실행 파일로 띄운다
    const root = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright');
    const exes = [];
    for (const d of (fs.existsSync(root) ? fs.readdirSync(root) : []).sort().reverse()) {
      for (const rel of ['chrome-headless-shell-win64/chrome-headless-shell.exe', 'chrome-win64/chrome.exe', 'chrome-win/chrome.exe']) {
        const f = path.join(root, d, rel); if (fs.existsSync(f)) exes.push(f);
      }
    }
    for (const f of exes) { try { browser = await chromium.launch({ executablePath: f }); break; } catch (e2) {} }
    if (!browser) throw e;
  }
  const page = await browser.newPage({ viewport: { width: 980, height: 1200 } });
  await page.goto('file:///' + path.resolve(html).replace(/\\/g, '/'));
  await page.waitForFunction(() => window.QA !== undefined);
  const qa = await page.evaluate(() => window.QA);
  fs.writeFileSync(path.join(outDir, 'qa_result.json'), JSON.stringify(qa, null, 1), 'utf-8');
  const flagged = [...new Set(qa.map(x => x.page))];
  for (const n of flagged) {
    const el = await page.$('#p' + n);
    if (el) await el.screenshot({ path: path.join(outDir, `qa_page_${n}.png`) });
  }
  await page.screenshot({ path: path.join(outDir, 'qa_overview.png'), fullPage: false });
  await browser.close();
  const errs = qa.filter(x => x.level !== 'warn').length;
  console.log(JSON.stringify({ issues: qa.length, errors: errs, warnings: qa.length - errs, pages: flagged }));
})().catch(e => { console.error(e.message); process.exit(2); });
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description='한글 PDF 조판 점검(Playwright)')
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--skip', default='1', help='점검에서 뺄 쪽(쉼표, 기본: 표지 1쪽)')
    ap.add_argument('--colors', default='#000000,#FFFFFF,#C00000')
    ap.add_argument('--margin', type=float, default=40.0, help='본문 영역 판정 여백(pt)')
    ap.add_argument('--min-fill', type=float, default=0.35)
    a = ap.parse_args(argv)
    out = a.out or os.path.splitext(a.pdf)[0] + '_점검'
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    pages = extract(a.pdf, out)
    cfg = {'skip': [int(x) for x in a.skip.split(',') if x.strip()], 'colors': a.colors.split(','),
           'margin': a.margin, 'minFill': a.min_fill, 'scale': 96 / 72}
    html = os.path.join(out, 'report.html')
    with open(html, 'w', encoding='utf-8') as f:
        f.write(HTML.replace('__DATA__', json.dumps(pages, ensure_ascii=False)).replace('__CFG__', json.dumps(cfg)))
    mjs = os.path.join(out, 'qa.cjs')
    with open(mjs, 'w', encoding='utf-8') as f:
        f.write(MJS)
    node = shutil.which('node')
    if not node:
        print('Node.js 가 없어 브라우저 점검을 건너뜁니다. report.html 을 브라우저로 열어 확인하세요:', html)
        return 1
    env = dict(os.environ)
    if not env.get('PLAYWRIGHT_MODULE'):     # 전역 설치(npm i -g playwright)도 찾는다
        npm = shutil.which('npm') or shutil.which('npm.cmd')
        if npm:
            try:
                root = subprocess.run([npm, 'root', '-g'], capture_output=True, text=True, timeout=30).stdout.strip()
                if root and os.path.isdir(os.path.join(root, 'playwright')):
                    env['PLAYWRIGHT_MODULE'] = os.path.join(root, 'playwright')
            except (OSError, subprocess.SubprocessError):
                pass
    r = subprocess.run([node, mjs, html, out], capture_output=True, text=True, encoding='utf-8', env=env)
    if r.returncode != 0 and 'playwright' in (r.stderr or '').lower():
        print('Playwright 를 찾지 못했습니다. `npm i -g playwright` 후 다시 실행하거나(브라우저는 자동 탐색), '
              'report.html 을 브라우저로 열면 같은 점검 결과를 볼 수 있습니다:', html)
    print((r.stdout or '').strip() or (r.stderr or '').strip())
    res = os.path.join(out, 'qa_result.json')
    if os.path.exists(res):
        qa = json.load(open(res, encoding='utf-8'))
        for x in qa[:80]:
            print(f"  {x['page']}쪽 [{x['kind']}] {x['msg']} — {x['text']}")
        print('보고서:', html)
    return 0 if r.returncode == 0 else r.returncode


if __name__ == '__main__':
    sys.exit(main())
