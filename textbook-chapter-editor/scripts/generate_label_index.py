#!/usr/bin/env python3
"""
generate_label_index.py — 全書 label 索引生成器

掃描 MyST Markdown (.md) 與 Jupyter Notebook (.ipynb) 教材檔案，提取所有
label，生成全書 label 索引（Markdown 表格），並執行：

  1. 重複 label 檢查（跨檔案）
  2. 斷鏈檢查：{prf:ref} / {ref} / {numref} / {eq} 引用的 label 是否存在

程式碼區塊（含 ```{code-cell}）與行內程式碼裡的 label、錨點與引用都只是示例，不收集。
任一輸入讀不到、或不是合法的 notebook 時，報出檔案並以退出碼 1 停下，不寫報告。

用法：
    python generate_label_index.py FILE [FILE ...] [-o OUTPUT.md]

範例：
    python3 generate_label_index.py chapters/*.md notebooks/*.ipynb -o label_index.md
"""

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

try:
    from myst_common import Document, parser, CODE
except ImportError as exc:
    sys.stderr.write(f"缺少解析依賴：{exc}；請按 SKILL.md 準備環境。\n")
    raise SystemExit(2)

DIRECTIVE_TYPE_NAMES = {
    "prf:theorem": "定理",
    "prf:lemma": "引理",
    "prf:corollary": "推論",
    "prf:proposition": "命題",
    "prf:definition": "定義",
    "prf:example": "例",
    "prf:remark": "注",
    "prf:proof": "證明",
    "prf:axiom": "公理",
    "prf:property": "性質",
    "prf:algorithm": "演算法",
    "exercise": "練習",
    "solution": "解答",
    "math": "方程",
    "figure": "圖",
    "table": "表",
    "admonition": "提示框",
}


def section_of(title):
    sec = re.search(r"§?\s*(\d+(?:\.\d+)*)", title)
    if sec:
        return f"§{sec.group(1)}"
    return title if len(title) <= 40 else title[:40]


def scan_text(lines, source, labels, refs, start_section="", pending_anchors=None,
              uncertain=None, where=None, line_base=0):
    """Use the shared token stream; notebook cells retain section/anchor state."""
    doc = Document("\n".join(lines), front=where is None or where == source)
    if uncertain is not None:
        for a, b, reason, raw in doc.notes:
            if '需要人工確認的位置' in reason:
                uncertain.append(dict(where=where or source, line=line_base+a, text=raw, reason=reason))
    section = start_section
    pending = pending_anchors if pending_anchors is not None else []

    def flush():
        for lab in pending:
            labels.append(dict(label=lab, kind="標題錨點", title=section,
                               section=section, source=source))
        pending.clear()

    def add_refs(tokens):
        for tok in tokens:
            if tok.type == 'myst_role' and tok.meta.get('name') in ('ref', 'prf:ref', 'numref', 'eq'):
                target = tok.content.strip()
                m = re.search(r'<([^<>]+)>$', target)
                target = m[1] if m else target
                refs.append(dict(label=target, section=section, source=source))
            if tok.children:
                add_refs(tok.children)

    for ev in doc.events:
        if ev.kind == 'target':
            pending.append(ev.text)
            continue
        if ev.kind == 'heading':
            if ev.text:
                section = section_of(ev.text)
            flush()
        else:
            flush()
        if ev.kind in ('inline', 'heading'):
            add_refs(ev.meta['tokens'])
        elif ev.kind == 'directive' and ev.meta['name'] not in CODE:
            add_refs(ev.meta['tokens'])
            if ev.meta.get('label'):
                labels.append(dict(label=ev.meta['label'], kind=DIRECTIVE_TYPE_NAMES.get(ev.meta['name'], ev.meta['name']),
                                   title=ev.text, section=section, source=source))
        elif ev.kind == 'math' and ev.meta.get('label'):
            labels.append(dict(label=ev.meta['label'], kind='方程', title='', section=section, source=source))
    if pending_anchors is None:
        flush()
    return section


def check_notebook(nb):
    """nbformat 4 的基本結構：頂層有 nbformat（≥4 的整數）、metadata（物件）、cells（陣列）；
    每個 cell 是物件，cell_type 是 markdown／code／raw，source 是字串或字串陣列，metadata 是物件。不合就丟出錯誤。"""
    if not isinstance(nb, dict):
        raise ValueError("不是 notebook（頂層不是物件）")
    if not isinstance(nb.get("nbformat"), int) or nb["nbformat"] < 4:
        raise ValueError("不是 nbformat 4 的 notebook（缺 nbformat 或版本太舊）")
    if not isinstance(nb.get("metadata"), dict):
        raise ValueError("不是 notebook（缺 metadata）")
    if not isinstance(nb.get("cells"), list):
        raise ValueError("不是 notebook（沒有 cells 陣列）")
    for i, cell in enumerate(nb["cells"]):
        if not isinstance(cell, dict) or cell.get("cell_type") not in ("markdown", "code", "raw"):
            raise ValueError(f"第 {i} 個 cell 不是合法的 cell（缺 cell_type 或類型不對）")
        src = cell.get("source")
        if not (isinstance(src, str) or (isinstance(src, list) and all(isinstance(s, str) for s in src))):
            raise ValueError(f"第 {i} 個 cell 的 source 不是字串或字串陣列")
        if not isinstance(cell.get("metadata"), dict):
            raise ValueError(f"第 {i} 個 cell 缺 metadata")
        if cell["cell_type"] == "code" and not (isinstance(cell.get("outputs"), list) and "execution_count" in cell
                                                and (cell["execution_count"] is None or isinstance(cell["execution_count"], int))):
            raise ValueError(f"第 {i} 個 code cell 缺 outputs 或 execution_count")
    if not isinstance(nb.get("nbformat_minor"), int):
        raise ValueError("不是 notebook（缺 nbformat_minor）")


def scan_file(path, labels, refs, uncertain=None):
    p = Path(path)
    source = p.as_posix()  # 用傳入的相對路徑區分不同目錄的同名檔案
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".ipynb":
        nb = json.loads(text)
        check_notebook(nb)
        section, pending = "", []
        for i, cell in enumerate(nb["cells"]):
            if cell["cell_type"] != "markdown":
                continue
            src = cell["source"]
            src = src.splitlines() if isinstance(src, str) else "".join(src).splitlines()
            section = scan_text(src, source, labels, refs, section, pending, uncertain, f"{source} 第 {i} 個 cell")
        for lab in pending:  # 檔案結束時還沒等到標題的錨點，歸到最後的章節
            labels.append(dict(label=lab, kind="標題錨點", title=section, section=section, source=source))
    else:
        scan_text(text.splitlines(), source, labels, refs, uncertain=uncertain)


# ---------------------------------------------------------------------------
# 報告生成
# ---------------------------------------------------------------------------

def natural_key(source):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", source)]


def build_report(labels, refs, uncertain=()):
    out = []
    out.append("# 全書 Label 索引\n")
    out.append(f"共 **{len(labels)}** 個 label，"
               f"**{len(refs)}** 處交叉引用。\n")

    # --- 按檔案（章）分組的索引表 ---
    by_source = OrderedDict()
    for item in sorted(labels, key=lambda d: natural_key(d["source"])):
        by_source.setdefault(item["source"], []).append(item)

    for source, items in by_source.items():
        out.append(f"\n## {source}\n")
        out.append("| Label | 類型 | 標題 | 章節位置 |")
        out.append("|---|---|---|---|")
        for it in items:
            title = it["title"].replace("|", "\\|")
            out.append(f"| `{it['label']}` | {it['kind']} "
                       f"| {title} | {it['section']} |")

    # --- 重複 label ---
    seen = {}
    dups = OrderedDict()
    for it in labels:
        if it["label"] in seen:
            dups.setdefault(it["label"], [seen[it["label"]]]).append(it)
        else:
            seen[it["label"]] = it
    out.append("\n## 重複 Label 檢查\n")
    if dups:
        for lab, occurrences in dups.items():
            locs = "；".join(f"{o['source']} {o['section']}"
                             for o in occurrences)
            out.append(f"- ⚠️ `{lab}`：{locs}")
    else:
        out.append("✅ 無重複 label。")

    # --- 斷鏈檢查 ---
    label_set = set(seen.keys())
    broken = [r for r in refs if r["label"] not in label_set]
    out.append("\n## 斷鏈檢查（引用了不存在的 label）\n")
    if broken:
        for r in broken:
            out.append(f"- ⚠️ `{r['label']}` — 引用於 "
                       f"{r['source']} {r['section']}")
    else:
        out.append("✅ 所有交叉引用均可解析。")

    # --- 需要人工確認的位置（已知限制） ---
    if uncertain:
        out.append("\n## 需要人工確認的位置\n")
        out.append("行內差分不一致或冒號式選項區的行原樣保留，請人工確認；可解析正文的 label 與引用仍按 token 收集。\n")
        for u in uncertain:
            text = u["text"].replace("`", "'")[:60]
            out.append(f"- {u['where']} 第 {u['line']} 行：{text}")

    out.append("")
    return "\n".join(out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="生成全書 label 索引")
    ap.add_argument("files", nargs="+", help=".md 或 .ipynb 檔案")
    ap.add_argument("-o", "--output", default="label_index.md",
                    help="輸出檔案路徑（預設 label_index.md）")
    args = ap.parse_args()

    labels, refs, failed, uncertain = [], [], [], []
    for f in args.files:
        try:
            scan_file(f, labels, refs, uncertain)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{f}：{type(e).__name__}：{e}")
    if failed:
        print("⚠️ 有輸入無法掃描，沒有寫出報告（部分掃描的結果不能當成完整檢查）：", file=sys.stderr)
        for x in failed:
            print(f"  - {x}", file=sys.stderr)
        sys.exit(1)

    report = build_report(labels, refs, uncertain)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"✅ 索引已寫入 {args.output}"
          f"（{len(labels)} 個 label，{len(refs)} 處引用）")

    if uncertain:
        print(f"⚠️ 有 {len(uncertain)} 行差分不一致，原樣保留；請看報告末尾「需要人工確認的位置」", file=sys.stderr)


if __name__ == "__main__":
    main()
