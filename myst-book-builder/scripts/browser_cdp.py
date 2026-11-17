"""共用的 MyST 靜態站指紋與隔離 Chromium CDP；只清理本次建立的資源。"""
from contextlib import contextmanager
import hashlib
import http.server
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote, urlparse
import urllib.request


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def browser_path(value=None):
    if value:
        path = Path(value)
        if not path.is_file():
            raise ValueError('找不到指定瀏覽器：' + str(path))
        return str(path.resolve()), 'explicit --browser'
    for name in ('chromium', 'chromium-browser', 'google-chrome', 'chrome', 'msedge'):
        if shutil.which(name):
            return shutil.which(name), 'PATH: ' + name
    for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        for relative in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
            if os.environ.get(key):
                candidate = Path(os.environ[key]) / relative
                if candidate.is_file():
                    return str(candidate), key + ': ' + relative
    raise ValueError('找不到 Chromium；請以 --browser 指定既有可執行檔，未自動安裝')


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get('children', []):
            yield from walk(child)


def source_headings(path):
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.ipynb':
        notebook = json.loads(text)
        text = '\n'.join(''.join(c.get('source', [])) for c in notebook['cells'] if c['cell_type'] == 'markdown')
    headings, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            mark = marker[1]
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if heading:
            title = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', heading[2])
            title = re.sub(r'[`*_]', '', title)
            headings.append(dict(level=len(heading[1]), text=' '.join(title.split())))
    return headings


def snapshot(html_dir, source_dir=None):
    """以 config 所載 toc 與 index 為準，不遞迴搜尋章節來源。"""
    root = Path(html_dir).resolve()
    config_path = root / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    projects = config.get('projects', [])
    if len(projects) != 1:
        raise ValueError('本版要求單一 MyST project；請分開處理各 project')
    project = projects[0]
    pages = [p for p in walk({'children': project.get('pages', [])}) if 'slug' in p]
    # 靜態匯出把首頁另存 index.json；其餘頁由 pages 的 toc 順序決定。
    index = json.loads((root / 'index.json').read_text(encoding='utf-8'))
    first_slug = index.get('slug', '')
    items = [dict(slug='', source=index.get('location'), title=index.get('frontmatter', {}).get('title', project.get('title', '首頁')))]
    for page in pages:
        slug = page['slug'].strip('/')
        if slug in ('', first_slug):
            continue
        items.append(dict(slug=slug, source=page.get('location'), title=page.get('title', slug)))
    if len({p['slug'] for p in items}) != len(items):
        raise ValueError('toc 含重複 slug')
    for item in items:
        slug = item['slug']
        html = root / (slug + '.html' if slug else 'index.html')
        if not html.is_file():
            html = root / slug / 'index.html'
        data_path = root / (slug + '.json' if slug else 'index.json')
        data = json.loads(data_path.read_text(encoding='utf-8'))
        item.update(source=(data.get('location') or item['source'] or '').lstrip('/'), title=data.get('frontmatter', {}).get('title') or item['title'],
                    html=html.relative_to(root).as_posix(), route='/' + slug, html_sha256=sha(html),
                    json=data_path.relative_to(root).as_posix(), json_sha256=sha(data_path))
        if source_dir:
            source = Path(source_dir) / str(item['source'])
            if not source.is_file():
                raise ValueError('找不到 toc 對應來源：' + str(source))
            item['source_sha256'] = sha(source)
            item['source_headings'] = source_headings(source)
        nodes = list(walk(data.get('mdast', {})))
        item['expected'] = dict(math=sum(n.get('type') in ('math', 'inlineMath') for n in nodes),
                                mermaid=sum(n.get('type') == 'mermaid' for n in nodes),
                                images=sum(n.get('type') == 'image' for n in nodes),
                                exercises=sum(n.get('type') == 'exercise' for n in nodes),
                                solutions=sum(n.get('type') == 'solution' for n in nodes))
        item['expected']['exercise_ids'] = [n.get('html_id') for n in nodes if n.get('type') == 'exercise' and n.get('html_id')]
        item['expected']['solution_targets'] = [next((c.get('html_id') for t in n.get('children', []) if t.get('type') == 'admonitionTitle' for c in walk(t) if c.get('type') == 'crossReference'), None) for n in nodes if n.get('type') == 'solution']
        references = []
        known_routes = {'/' + p['slug'] for p in items}
        for node in nodes:
            if node.get('type') != 'crossReference' or not node.get('html_id') or not (str(node.get('kind', '')).startswith('proof:') or node.get('kind') in ('exercise', 'solution')):
                continue
            template = node.get('template', '')
            target = urlparse(node.get('url') or item['route'])
            route = target.path.rstrip('/') or '/'
            if target.scheme or target.netloc or route not in known_routes or '%s' not in template or node.get('enumerator') is None:
                continue
            references.append(dict(route=route, fragment=node['html_id'], label=' '.join(template.replace('%s', str(node['enumerator'])).split())))
        item['generated_references'] = references
        authored = []
        for node in nodes:
            if node.get('type') != 'link' or not node.get('url'):
                continue
            target = urlparse(node['url'])
            if target.scheme or target.netloc or not target.fragment:
                continue
            route = (target.path.rstrip('/') or '/') if target.path else item['route']
            label = ' '.join(''.join(c.get('value', '') for c in walk(node) if c.get('type') in ('text', 'inlineCode')).split())
            authored.append(dict(route=route, fragment=target.fragment, label=label))
        item['authored_links'] = authored
        item['ast_headings'] = [dict(level=n['depth'], text=' '.join(''.join(c.get('value', '') for c in walk(n) if c.get('type') in ('text', 'inlineCode')).split())) for n in nodes if n.get('type') == 'heading']
    return dict(config_sha256=sha(config_path), toc_sha256=hashlib.sha256(json.dumps(project.get('pages'), sort_keys=True).encode()).hexdigest(), pages=items)


@contextmanager
def serve(directory):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def log_message(self, *args):
            pass
        def translate_path(self, path):
            translated = Path(super().translate_path(path))
            # MyST 路由 /slug 和 /；磁碟可能用 slug/index.html 或 slug.html。
            # 直接回應 route，避免把 /index.html 當成 MyST 的頁面 slug。
            if translated.is_dir() and (translated / 'index.html').is_file():
                return str(translated / 'index.html')
            if not translated.suffix and translated.with_suffix('.html').is_file():
                return str(translated.with_suffix('.html'))
            return str(translated)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class Browser:
    def __init__(self, executable, timeout=45):
        self.executable, self.timeout = executable, timeout
        self.process = self.ws = self.profile = None
        self.counter = 0
        self.events = []

    def __enter__(self):
        try:
            import websocket
            self.profile = tempfile.mkdtemp(prefix='myst-print-')
            self.process = subprocess.Popen([self.executable, '--headless=new', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + self.profile, 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + self.timeout
            active = Path(self.profile) / 'DevToolsActivePort'
            while not active.exists():
                if self.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Chromium 啟動失敗或 CDP 逾時')
                time.sleep(.1)
            port = active.read_text().splitlines()[0]
            with urllib.request.urlopen('http://127.0.0.1:' + port + '/json/list', timeout=5) as response:
                tabs = json.load(response)
            url = next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page')
            self.ws = websocket.create_connection(url, timeout=self.timeout, suppress_origin=True)
            for method in ('Page.enable', 'Runtime.enable', 'Network.enable'):
                self.call(method)
            self.call('Page.addScriptToEvaluateOnNewDocument', source="try { localStorage.setItem('myst:theme','light'); } catch(e) {} window.matchMedia = ((original) => q => q.includes('prefers-color-scheme') ? {matches:false,media:q,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}} : original(q))(window.matchMedia.bind(window));")
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.ws:
            self.ws.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)

    def call(self, method, **params):
        self.counter += 1
        self.ws.send(json.dumps(dict(id=self.counter, method=method, params=params)))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            result = json.loads(self.ws.recv())
            if result.get('id') == self.counter:
                if 'error' in result:
                    raise RuntimeError(method + ': ' + str(result['error']))
                return result.get('result', {})
            self.events.append(result)
        raise RuntimeError('CDP 逾時：' + method)

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
        if result.get('exceptionDetails'):
            raise RuntimeError('JavaScript 執行失敗：' + str(result['exceptionDetails']))
        return result.get('result', {}).get('value')

    def load(self, origin, page):
        url = origin + quote(page['route'], safe='/')
        self.events = []
        self.call('Page.navigate', url=url)
        deadline = time.monotonic() + self.timeout
        last = None
        while time.monotonic() < deadline:
            last = self.evaluate(COLLECT_JS)
            if last:
                problems = ready_problems(last, page['expected'], url)
                if not problems:
                    # 連續兩次通過，避免 hydration 中間態。
                    time.sleep(.3)
                    last = self.evaluate(COLLECT_JS)
                    if not ready_problems(last, page['expected'], url):
                        statuses = [e['params']['response']['status'] for e in self.events if e.get('method') == 'Network.responseReceived' and e['params'].get('type') == 'Document' and e['params']['response']['url'] == url]
                        if statuses != [200]:
                            raise RuntimeError('頁面請求不是唯一的 HTTP 200：' + str(statuses))
                        return last
            time.sleep(.2)
        raise RuntimeError('印前／QA 就緒失敗：' + str(ready_problems(last or {}, page['expected'], url)))


COLLECT_JS = r"""(() => {
const a=document.querySelector('article.article')||document.querySelector('article');
if (!a) return {href:location.href,article:false};
document.querySelectorAll('details').forEach(d=>d.open=true);
a.querySelectorAll('img').forEach(i=>i.loading='eager');
const fib=e=>e&&Object.keys(e).some(k=>k.startsWith('__reactFiber'));
const blocks=[...a.children];
const svg=[...a.querySelectorAll('svg[id^="mermaid-"]')];
const clean=s=>(s||'').replace(/\s+/g,' ').trim();
const visible=e=>{if(!e||!e.getBoundingClientRect().height)return false;for(let n=e;n;n=n.parentElement){const s=getComputedStyle(n);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
const semantic=[...a.querySelectorAll('.myst-exercise,.myst-solution')].map(e=>{
 const h=e.querySelector('.myst-exercise-title,.myst-solution-title')||e.querySelector('summary');
 const title=clean(h?.textContent);const body=e.querySelector('.myst-exercise-body,.myst-solution-body,.details-body');
 return {id:e.id,title,solution:e.matches('.myst-solution')||/^(Solution\b|解答)/.test(title),exercise:/^(Exercise\b|习题|習題)/.test(title),
 target:h?.querySelector('a[href]')?decodeURIComponent(new URL(h.querySelector('a[href]').href).hash.slice(1)):null,
 body:clean(body?.innerText),body_visible:visible(body),open:e.tagName!=='DETAILS'||e.open};
});
return {href:location.href,article:true,ready:document.readyState,
 hydrated:fib(a.querySelector('h1')||a)&&(!blocks.length||fib(blocks[blocks.length-1])),fonts:document.fonts.status,
 title:clean(a.querySelector('h1')?.textContent),
 math:a.querySelectorAll('.katex').length,math_errors:a.querySelectorAll('.katex-error').length,
 mermaid:svg.map(s=>({labels:[...s.querySelectorAll('foreignObject,text')].map(n=>clean(n.textContent)).filter(Boolean),
 paths:s.querySelectorAll('path').length,width:s.getBoundingClientRect().width,height:s.getBoundingClientRect().height,
 visible:getComputedStyle(s).visibility!=='hidden'&&getComputedStyle(s).display!=='none'&&Number(getComputedStyle(s).opacity)>0})),
 images:[...a.querySelectorAll('img')].map(i=>({src:i.getAttribute('src'),complete:i.complete,width:i.naturalWidth})),
 solutions:semantic.filter(e=>e.solution),exercises:semantic.filter(e=>e.exercise&&!e.solution),
 headings:[...a.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h=>({level:Number(h.tagName[1]),text:clean(h.textContent).replace(/\s*¶$/,'')})),
 ids:[...document.querySelectorAll('[id]')].map(n=>n.id),
 links:[...a.querySelectorAll('a[href]')].map(n=>({href:n.href,text:clean(n.textContent)})),
 widths:[...a.querySelectorAll('pre,table,svg,img,.katex-display')].filter(e=>e.scrollWidth>e.clientWidth+2||e.getBoundingClientRect().right>innerWidth+2).map(e=>({tag:e.tagName,width:e.scrollWidth,available:e.clientWidth})),
 errors:[...a.querySelectorAll('pre')].map(n=>n.textContent).filter(s=>s.startsWith('Error parsing mermaid'))};
})()"""


def ready_problems(state, expected, url):
    errors = []
    for key, value in (('href', url), ('article', True), ('ready', 'complete'), ('hydrated', True), ('fonts', 'loaded')):
        if state.get(key) != value:
            errors.append(key + ': ' + repr(state.get(key)))
    if state.get('math', 0) < expected['math'] or state.get('math_errors'):
        errors.append('公式缺失／渲染錯誤')
    if len(state.get('mermaid', [])) != expected['mermaid'] or state.get('errors'):
        errors.append('Mermaid 數量不符／解析錯誤')
    for graph in state.get('mermaid', []):
        if not graph['visible'] or not graph['labels'] or not graph['paths'] or graph['width'] <= 0 or graph['height'] <= 0:
            errors.append('Mermaid 空白／不可見')
    if len(state.get('images', [])) < expected['images'] or any(not i['complete'] or not i['width'] for i in state.get('images', [])):
        errors.append('圖片缺失／損壞')
    solutions = state.get('solutions', [])
    exercises = state.get('exercises', [])
    if len(solutions) != expected['solutions'] or any(not s['body'] or not s['body_visible'] or not s['open'] for s in solutions):
        errors.append('解答缺失／數量不符／內容未展開')
    if len(exercises) != expected['exercises'] or any(not e['body'] or not e['body_visible'] or not e['open'] for e in exercises):
        errors.append('習題缺失／數量不符／內容未展開')
    if sorted(e['id'] for e in exercises if e['id']) != sorted(expected['exercise_ids']):
        errors.append('習題 AST 目標不符')
    wanted = sorted(t for t in expected['solution_targets'] if t)
    actual = sorted(s['target'] for s in solutions if s['target'])
    if actual != wanted:
        errors.append('解答 AST 對應習題不符')
    return errors
