"""按 toc 檢查 hydrated MyST 網站；阻斷仍寫出完整 JSON 報告。"""
import argparse
from pathlib import Path
from urllib.parse import unquote, urlparse
from browser_cdp import Browser, browser_path, serve, sha, snapshot, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--source-dir', type=Path)
    args = parser.parse_args()
    report = dict(schema=1, success=False, errors=[], pages=[], external_links=[], script_sha256=sha(__file__),
                  shared_script_sha256=sha(Path(__file__).with_name('browser_cdp.py')),
                  source_dir=str(args.source_dir.resolve()) if args.source_dir else None)
    try:
        report['inputs'] = snapshot(args.html_dir, args.source_dir)
        executable, _ = browser_path(args.browser)
        with serve(args.html_dir) as origin, Browser(executable) as browser:
            report['qa_origin'] = origin
            for page in report['inputs']['pages']:
                item = dict(slug=page['slug'], source=page['source'], errors=[])
                report['pages'].append(item)
                try:
                    state = browser.load(origin, page)
                    item['state'] = state
                    levels = [h['level'] for h in state['headings']]
                    if not levels or levels[0] != 1 or any(b > a + 1 for a, b in zip(levels, levels[1:])):
                        item['errors'].append('標題層級跳號／缺少 h1')
                    expected_headings = page.get('source_headings') or [dict(level=1, text=page['title'])] + page['ast_headings']
                    if expected_headings and expected_headings[0]['level'] != 1:
                        expected_headings = [dict(level=1, text=page['title'])] + expected_headings
                    item['expected_headings'] = expected_headings
                    if state['headings'] != expected_headings:
                        item['errors'].append('來源／AST 與渲染標題文字或順序不符')
                    if state['title'] != page['title']:
                        item['errors'].append('toc 章標題與渲染標題不符')
                    item['width_risks'] = state['widths']
                    item['console_exceptions'] = [e['params'] for e in browser.events if e.get('method') == 'Runtime.exceptionThrown']
                    if item['console_exceptions']:
                        item['errors'].append('JavaScript 例外')
                except Exception as exc:
                    item['errors'].append(str(exc))
            known = {p['slug']: p for p in report['pages']}
            paths = {p['html']: p['slug'] for p in report['inputs']['pages']}
            paths.update({p['slug']: p['slug'] for p in report['inputs']['pages']})
            paths['index.html'] = ''
            for item in report['pages']:
                for link in item.get('state', {}).get('links', []):
                    parsed = urlparse(link['href'])
                    if parsed.scheme not in ('http', 'https'):
                        continue
                    if parsed.netloc != urlparse(origin).netloc:
                        report['external_links'].append(dict(source=item['slug'], **link, checked=False))
                        continue
                    path = unquote(parsed.path).strip('/')
                    if path.endswith('/index.html'):
                        path = path[:-11]
                    target = known.get(paths.get(path))
                    if not target or 'state' not in target or (parsed.fragment and unquote(parsed.fragment) not in target['state']['ids']):
                        item['errors'].append('書內連結目標不存在：' + link['href'])
            report['errors'] = [dict(slug=p['slug'], error=e) for p in report['pages'] for e in p['errors']]
            report['success'] = not report['errors']
    except Exception as exc:
        report['errors'].append(dict(error=str(exc)))
    write_json(args.out_dir / 'qa_report.json', report)
    print(str(args.out_dir / 'qa_report.json') + ': ' + ('通過' if report['success'] else '阻斷'))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
