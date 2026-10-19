"""Find literal ** remaining in parsed text; candidates require human review."""
import argparse
import json
import sys
from pathlib import Path

try:
    from myst_common import Document, CODE, PATH, iter_text
except ImportError as exc:
    sys.stderr.write(f'缺少解析依賴：{exc}；請按 SKILL.md 準備環境。\n')
    raise SystemExit(2)


def candidates(text, front=True):
    doc = Document(text, front=front)
    result = []
    for ev in doc.events:
        if ev.kind not in ('inline', 'heading', 'directive'):
            continue
        if ev.kind == 'directive' and ev.meta['name'] in CODE | PATH:
            continue
        for line, value in iter_text(ev.meta['tokens'], ev.line):
            if '**' in value:
                result.append((line, value))
    return result


def main():
    ap = argparse.ArgumentParser(description='檢查解析後殘留的 **（只列候選，不自動修改）')
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()
    findings, errors = [], []
    for path in args.files:
        try:
            raw = Path(path).read_text(encoding='utf-8')
            if Path(path).suffix == '.ipynb':
                from generate_label_index import check_notebook
                nb = json.loads(raw)
                check_notebook(nb)
                texts = [(f'{path} 第 {i} 格', ''.join(c['source'])) for i, c in enumerate(nb['cells'])
                         if c['cell_type'] == 'markdown']
            else:
                texts = [(path, raw)]
            for where, text in texts:
                findings += [f'{where} 第 {line} 行所在區塊：{value}' for line, value in candidates(text, Path(path).suffix != '.ipynb')]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f'{path}：{exc}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 2
    print('\n'.join(findings) if findings else '未發現文字 token 殘留 **。')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
