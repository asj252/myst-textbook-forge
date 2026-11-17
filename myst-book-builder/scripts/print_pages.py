"""以同一硬門列印 toc 頁面，產生帶實際 origin 的可驗證交接清單。"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
from browser_cdp import Browser, browser_path, serve, sha, snapshot, write_json, COLLECT_JS, ready_problems


CSS = r"""
@page {size:A4; margin:15mm 14mm;}
html,body {background:white!important;color:black!important;}
.myst-skip-to-article,.skip-to-article,.myst-top-nav,.myst-primary-sidebar,.myst-footer-links,.myst-outline,nav,footer,button[title],.myst-fm-block-header,[class*="launch"],[class*="Launch"] {display:none!important;}
main.article-grid,article.article-grid {display:block!important;margin:0!important;padding:0!important;max-width:none!important;}
article {width:100%!important;max-width:none!important;padding:0!important;margin:0!important;}
article>* {max-width:none!important;margin-left:0!important;margin-right:0!important;}
pre,pre *,code {white-space:break-spaces!important;overflow-wrap:anywhere!important;word-break:break-word!important;}
pre {overflow:visible!important;}
article p code {white-space:break-spaces!important;overflow-wrap:anywhere!important;}
figure,svg,img,.katex-display,tr,.myst-print-graph,details,.myst-exercise {break-inside:avoid;}
h1,h2,h3,h4 {break-after:avoid;}
details>* {display:block;}
"""

TRANSLATE_JS = r"""((options) => {
const {lang,refs,authored=[]}=options;
const a=document.querySelector('article.article')||document.querySelector('article');
const clean=s=>(s||'').replace(/\s+/g,' ').trim();
const signature=r=>JSON.stringify([r.route,r.fragment,r.label]);
const same=(r,s)=>signature(r)===signature(s);
if(lang!=='preserve'){
 const blocked=[];
 for(const ref of refs){
  const count=refs.filter(r=>same(r,ref)).length;
  const matches=[...a.querySelectorAll('a[href]')].filter(link=>{
   if((link.getAttribute('title')||'').startsWith('Link to this '))return false;
   const u=new URL(link.href);return u.origin===location.origin&&(u.pathname.replace(/\/$/,'')||'/')===ref.route&&decodeURIComponent(u.hash.slice(1))===ref.fragment&&clean(link.textContent)===ref.label;
  });
  if(authored.some(r=>same(r,ref))||matches.length>count)blocked.push(ref);
 }
 if(blocked.length)return {blocked,reason:'生成引用與作者普通連結無法唯一映射；保留文字並停止換字'};
}
const words={Theorem:['定理','定理'],Definition:['定义','定義'],Example:['例','例'],Property:['性质','性質'],Proof:['证明','證明'],Exercise:['习题','習題'],Solution:['解答','解答'],Lemma:['引理','引理'],Remark:['注','註'],Corollary:['推论','推論'],Proposition:['命题','命題'],Algorithm:['算法','演算法'],Conjecture:['猜想','猜想'],Axiom:['公理','公理'],Criterion:['判据','判據'],Observation:['观察','觀察'],Assumption:['假设','假設'],Notation:['记号','記號']};
const all=()=>{let w=document.createTreeWalker(a,NodeFilter.SHOW_TEXT),n,out=[];while(n=w.nextNode())out.push(n);return out;};
const nodes=all(),targets=[];
for(const n of nodes){
 const title=n.parentElement.closest('.myst-proof-title,.myst-exercise-title');
 const link=n.parentElement.closest('a[href]');
 const url=link?new URL(link.href):null;
 const generated=link&&url.origin===location.origin&&refs.some(r=>r.route===(url.pathname.replace(/\/$/,'')||'/')&&r.fragment===decodeURIComponent(url.hash.slice(1))&&r.label===link.textContent.replace(/\s+/g,' ').trim());
 if(!title&&!generated)continue;
 const m=n.nodeValue.match(/^(\s*)([A-Za-z]+)(?=\s|$)/);
 if(m&&words[m[2]]&&lang!=='preserve')targets.push({n,before:n.nodeValue,word:m[2],prefix:m[1]});
}
const set=new Set(targets.map(t=>t.n)), other=()=>all().filter(n=>!set.has(n)).map(n=>n.nodeValue);
const structure=()=>[...a.querySelectorAll('*')].map(e=>[e.tagName,e.id,e.getAttribute('href'),e.children.length]);
const before=other(), shape=structure();
for(const t of targets){
 // 保持所有節點、href 和編號，解答的連接詞一併本地化。
 if(t.word==='Solution'&&/^\s*Solution to\s*$/.test(t.before))t.n.nodeValue=lang==='zh-Hant'?'解答：':'解答：';
 else t.n.nodeValue=t.prefix+words[t.word][lang==='zh-Hant'?1:0]+t.before.slice(t.prefix.length+t.word.length);
}
window.__mystPrintTranslation={targets,other:other(),structure:structure(),all};
targets.forEach(t=>t.after=t.n.nodeValue);
return {targets:targets.map(t=>({before:t.before,after:t.n.nodeValue})),non_target_before:before,non_target_after:other(),structure_before:shape,structure_after:structure(),non_target_unchanged:JSON.stringify(before)===JSON.stringify(other()),structure_unchanged:JSON.stringify(shape)===JSON.stringify(structure())};
})"""

FIT_JS = r"""(() => {
const a=document.querySelector('article.article')||document.querySelector('article');
const width=182*96/25.4,height=(297-30)*96/25.4;
let records=[];
// 圖與緊鄰小標題在同一可分頁單元；把標題高度納入 SVG 上限。
for(const s of a.querySelectorAll('svg[id^="mermaid-"]')){
 const f=s.closest('figure')||s.parentElement;
 let h=f.previousElementSibling;
 if(h&&/^H[2-6]$/.test(h.tagName)){
  const group=document.createElement('div');group.className='myst-print-graph';h.before(group);group.append(h,f);
 }
 const group=f.closest('.myst-print-graph')||f;
 const heading=[...group.children].filter(e=>/^H[1-6]$/.test(e.tagName)).reduce((v,e)=>v+e.getBoundingClientRect().height+parseFloat(getComputedStyle(e).marginTop||0)+parseFloat(getComputedStyle(e).marginBottom||0),0);
 const rect=s.getBoundingClientRect(), limit=height-heading-35;
 const ratio=Math.min(1,width/rect.width,limit/rect.height);
 s.style.width=rect.width*ratio+'px';s.style.height=rect.height*ratio+'px';s.style.maxWidth='100%';
 records.push({kind:'mermaid',ratio,available_height:limit,heading_height:heading,labels:[...s.querySelectorAll('foreignObject,text')].map(e=>e.textContent.replace(/\s+/g,' ').trim()).filter(Boolean)});
}
for(const e of a.querySelectorAll('table,.katex-display,img')){
 if(e.closest('svg'))continue;
 const r=e.getBoundingClientRect();const ratio=Math.min(1,width/Math.max(e.scrollWidth,r.width),height/r.height);
 if(ratio<1)e.style.zoom=ratio;
 records.push({kind:e.tagName,ratio});
}
return records;
})()"""

GEOMETRY_JS = r"""(() => {
const a=document.querySelector('article.article')||document.querySelector('article');
const left=a.getBoundingClientRect().left,right=left+182*96/25.4;
return [...a.querySelectorAll('pre,code,table,img,svg[id^="mermaid-"],.katex-display,.myst-print-graph')].map(e=>{
 const r=e.getBoundingClientRect();return {tag:e.tagName,kind:e.className?.baseVal||e.className,left:r.left,right:r.right,width:r.width,height:r.height,scroll_width:e.scrollWidth,client_width:e.clientWidth,
 overflow:r.left<left-2||r.right>right+2||(e.tagName==='PRE'&&e.scrollWidth>e.clientWidth+2),too_tall:(e.matches('svg[id^="mermaid-"],.myst-print-graph')&&r.height>(297-30)*96/25.4+2)};
});})()"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--expect', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--lang', choices=['preserve', 'zh-Hans', 'zh-Hant'], default='preserve')
    parser.add_argument('--pages', nargs='+')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / 'print_manifest.json'
    if manifest_path.exists():
        parser.error('輸出清單已存在；請使用新目錄以保留舊證據')
    manifest = dict(schema=1, success=False, complete=False, pages=[], errors=[], print_origin=None,
                    qa_sha256=sha(args.expect), script_sha256=sha(__file__), lang=args.lang)
    index = dict(schema=1, success=False, print_origin=None, pages=[], visual_review_required=True)
    try:
        qa = json.loads(args.expect.read_text(encoding='utf-8'))
        if not qa.get('success'):
            raise ValueError('QA 未通過')
        inputs = snapshot(args.html_dir, qa.get('source_dir'))
        if inputs != qa['inputs']:
            raise ValueError('QA 指紋不符：config／toc／來源／HTML／頁面 JSON 已變動')
        manifest['inputs'] = inputs
        selected = [p for p in inputs['pages'] if args.pages is None or (p['slug'] or 'index') in args.pages]
        if args.pages and len(selected) != len(set(args.pages)):
            raise ValueError('--pages 含未知或重複 slug')
        executable, _ = browser_path(args.browser)
        with serve(args.html_dir) as origin, Browser(executable) as browser:
            manifest['print_origin'] = index['print_origin'] = origin
            browser.call('Emulation.setDeviceMetricsOverride', width=round(182*96/25.4), height=1200, deviceScaleFactor=1, mobile=False)
            browser.call('Emulation.setEmulatedMedia', media='print')
            for number, page in enumerate(selected):
                evidence = dict(slug=page['slug'], success=False)
                index['pages'].append(evidence)
                try:
                    before = browser.load(origin, page)
                    browser.call('DOM.enable')
                    browser.evaluate('document.documentElement.classList.remove("dark");document.documentElement.classList.add("light");true')
                    browser.evaluate('(()=>{let s=document.createElement("style");s.textContent=' + json.dumps(CSS) + ';document.head.appendChild(s);return true})()')
                    translation = browser.evaluate('(' + TRANSLATE_JS + ')(' + json.dumps(dict(lang=args.lang, refs=page['generated_references'], authored=page['authored_links'])) + ')')
                    if translation.get('blocked'):
                        raise ValueError(translation['reason'] + ': ' + repr(translation['blocked']))
                    if not translation['non_target_unchanged'] or not translation['structure_unchanged']:
                        raise ValueError('換字改到非目標文字／結構')
                    for kind in ('non_target', 'structure'):
                        for stage in ('before', 'after'):
                            values = translation.pop(kind + '_' + stage)
                            translation[kind + '_' + stage + '_sha256'] = hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
                    evidence['translation'] = translation
                    evidence['fit'] = browser.evaluate(FIT_JS)
                    time.sleep(.3)
                    after = browser.evaluate(COLLECT_JS)
                    translation_stable = browser.evaluate('(()=>{const t=window.__mystPrintTranslation;return t.targets.every(x=>x.n.isConnected&&x.n.nodeValue===x.after)&&JSON.stringify(t.other)===JSON.stringify(t.all().filter(n=>!t.targets.some(x=>x.n===n)).map(n=>n.nodeValue))})()')
                    if not translation_stable:
                        raise ValueError('換字在列印前被重繪／非目標文字變動')
                    errors = ready_problems(after, page['expected'], origin + page['route'])
                    geometry = browser.evaluate(GEOMETRY_JS)
                    errors += [str(g) for g in geometry if g['overflow'] or g['too_tall']]
                    if errors:
                        raise ValueError('列印幾何／就緒阻斷：' + repr(errors))
                    evidence.update(before=before, after=after, geometry=geometry,
                                    small_objects=[r for r in evidence['fit'] if r['ratio'] < .6])
                    # 截圖只是輔助；PDF 全圖與完整標籤、箭頭必須另行視覺驗收。
                    screenshot = args.evidence / (str(number).zfill(3) + '.png')
                    screenshot.write_bytes(base64.b64decode(browser.call('Page.captureScreenshot', captureBeyondViewport=True)['data']))
                    part = args.out_dir / (str(number).zfill(3) + '-' + (page['slug'].replace('/', '-') or 'index') + '.pdf')
                    result = browser.call('Page.printToPDF', printBackground=True, preferCSSPageSize=True, displayHeaderFooter=False, generateTaggedPDF=True)
                    part.write_bytes(base64.b64decode(result['data']))
                    evidence.update(success=True, part=str(part.resolve()), part_sha256=sha(part))
                    evidence_file = args.evidence / (str(number).zfill(3) + '.json')
                    write_json(evidence_file, evidence)
                    manifest['pages'].append(dict(page, part=str(part.resolve()), part_sha256=sha(part),
                                                  evidence=str(evidence_file.resolve()), evidence_sha256=sha(evidence_file)))
                except Exception as exc:
                    evidence['error'] = str(exc)
                    raise
            manifest['complete'] = args.pages is None and len(manifest['pages']) == len(inputs['pages'])
            manifest['success'] = index['success'] = len(manifest['pages']) == len(selected)
    except Exception as exc:
        manifest['errors'].append(str(exc))
    index_file = args.evidence / 'index.json'
    write_json(index_file, index)
    manifest['evidence_index'] = str(index_file.resolve())
    manifest['evidence_index_sha256'] = sha(index_file)
    write_json(manifest_path, manifest)
    print(str(manifest_path) + ': ' + ('通過；待 PDF 視覺復核' if manifest['success'] else '阻斷：' + '; '.join(manifest['errors'])))
    return 0 if manifest['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
