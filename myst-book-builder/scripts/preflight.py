"""探測指定 Python 的建書／瀏覽器及目前 Python 的 PDF 能力；不安裝依賴。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from browser_cdp import browser_path, write_json

PROBE = """import sys,json,importlib.util,importlib.metadata as m
names=['jupyter-book','nbformat','nbclient','websocket-client','pypdf']
versions={}
for name in names:
 try: versions[name]=m.version(name)
 except m.PackageNotFoundError: versions[name]=None
print(json.dumps(dict(python=sys.executable,version=sys.version,packages=versions)))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', dest='python_exe')
    parser.add_argument('--browser')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    report = dict(success=False, errors=[], selection='explicit --python' if args.python_exe else 'current sys.executable')
    try:
        executable = args.python_exe or sys.executable
        if not Path(executable).is_file():
            executable = shutil.which(executable)
        if not executable:
            raise ValueError('找不到指定 Python')
        result = subprocess.run([executable, '-c', PROBE], capture_output=True, text=True, encoding='utf-8', timeout=30)
        if result.returncode:
            raise ValueError('指定 Python 探測失敗：' + result.stderr)
        report['build_environment'] = json.loads(result.stdout)
        own = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, encoding='utf-8', timeout=30)
        report['script_environment'] = json.loads(own.stdout)
        report['browser'], report['browser_selection'] = browser_path(args.browser)
        if os.name == 'nt':
            environment = dict(os.environ, MYST_BROWSER_EXE=report['browser'])
            browser_version = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                '(Get-Item -LiteralPath $env:MYST_BROWSER_EXE).VersionInfo.ProductVersion'], env=environment,
                capture_output=True, text=True, encoding='utf-8', timeout=15)
        else:
            browser_version = subprocess.run([report['browser'], '--version'], capture_output=True, text=True, encoding='utf-8', timeout=15)
        report['browser_version'] = dict(exit_code=browser_version.returncode, value=browser_version.stdout.strip(), stderr=browser_version.stderr.strip())
        version = subprocess.run([executable, '-m', 'jupyter_book', '--version'], capture_output=True, text=True, encoding='utf-8', timeout=30)
        report['jb_cli'] = dict(exit_code=version.returncode, stdout=version.stdout.strip(), stderr=version.stderr.strip())
        for name in ('jupyter-book',):
            if not report['build_environment']['packages'][name]:
                report['errors'].append('指定 Python 缺少建書依賴：' + name)
        if not report['script_environment']['packages']['websocket-client']:
            report['errors'].append('QA／列印的目前 Python 缺少 websocket-client；可改用另一個既有 Python')
        report['pdf_processing_available_here'] = bool(report['script_environment']['packages']['pypdf'])
        report['node'] = shutil.which('node')
        if report['node']:
            report['node_version'] = subprocess.run([report['node'], '--version'], capture_output=True, text=True, timeout=15).stdout.strip()
        if version.returncode:
            report['errors'].append('JB CLI 失敗')
        elif not version.stdout.strip().lstrip('v').startswith('2.'):
            report['errors'].append('本版僅支援 Jupyter Book 2；請選擇相容的既有環境')
        if browser_version.returncode or not report['browser_version']['value']:
            report['errors'].append('無法探測瀏覽器版本')
        if not report['node']:
            report['errors'].append('PATH 找不到 Node；請選擇既有執行環境')
        report['success'] = not report['errors']
    except Exception as exc:
        report['errors'].append(str(exc))
    write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
