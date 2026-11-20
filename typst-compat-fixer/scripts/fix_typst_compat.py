#!/usr/bin/env python3
"""
fix_typst_compat.py — 將 MyST Markdown / Jupyter Notebook 中的 LaTeX 與 MyST 語法
批次轉換為 Typst PDF 匯出相容的形式。

依 MyST 區塊和行內語法確認原文位置，修復數學與簡單的 directive 標籤選項。
保護程式碼區、HTML、YAML、連結目標與標題，以及 notebook 的非 Markdown 格。

處理項目:
  1. 數學環境中的 \\color{#XXXXXX} / \\textcolor{#XXXXXX} → Typst 命名顏色
     (示例調色盤有顯式映射:#1F4E9C → blue 等;與 textbook-visual-style 的示例配色一致)
  2. Typst 不支援或轉換器有 bug 的 LaTeX 命令替換(按完整命令名比對)
     (\\Uparrow, \\Downarrow, \\hbar, \\blacksquare, \\iff, \\bmod,
      \\longrightarrow, \\longleftrightarrow, \\notin, {\\sf T},
      \\displaystyle, \\scriptstyle, 簡單 \\xrightarrow{...})
  3. MyST directive 的 :name: → :label:(只改 directive 開頭緊接的選項行)
  4. 檢測並報告需人工(由執行者)判斷的項目:
     - 前向引用(引用出現在 label 定義之前;跳過程式碼示例)
     - 未定義的引用(跳過程式碼示例;示例裡的定義也不算定義)
     - 複雜的 \\xrightarrow(含可選參數或嵌套大括號)
     - 未在調色盤中的十六進制顏色(回報自動映射結果與色差/色相告警供確認)

用法:
  python fix_typst_compat.py INPUT [-o OUTPUT] [--in-place] [--report REPORT.json]
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import colorsys
from copy import deepcopy
import json
import os
import re
import sys
from tempfile import NamedTemporaryFile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:  # 也支援 python -I 直接執行。
    sys.path.insert(0, str(SCRIPTS))
try:
    from myst_regions import View, escaped, regions, valid_label
except ImportError as error:
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(
        f"無法載入 MyST 解析依賴（{error}）。"
        f'請執行 python -m pip install -r "{SCRIPTS / "requirements.txt"}"'
    ) from error

# ---------------------------------------------------------------------------
# 1. 顏色映射表
# ---------------------------------------------------------------------------

# Typst 內建命名顏色(同時在 KaTeX/HTML 中有定義,確保雙端相容)
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black":   (0x00, 0x00, 0x00),
    "gray":    (0x80, 0x80, 0x80),
    "silver":  (0xC0, 0xC0, 0xC0),
    "white":   (0xFF, 0xFF, 0xFF),
    "navy":    (0x00, 0x00, 0x80),
    "blue":    (0x00, 0x00, 0xFF),
    "aqua":    (0x00, 0xFF, 0xFF),
    "teal":    (0x00, 0x80, 0x80),
    "purple":  (0x80, 0x00, 0x80),
    "fuchsia": (0xFF, 0x00, 0xFF),
    "maroon":  (0x80, 0x00, 0x00),
    "red":     (0xFF, 0x00, 0x00),
    "orange":  (0xFF, 0xA5, 0x00),
    "yellow":  (0xFF, 0xFF, 0x00),
    "olive":   (0x80, 0x80, 0x00),
    "green":   (0x00, 0x80, 0x00),
    "lime":    (0x00, 0xFF, 0x00),
}

# 示例調色盤的顯式語義映射(優先於距離匹配;與 textbook-visual-style 的示例配色一致)。
# 換成自己的配色時,按角色把這裡一起換掉。可自行擴充。
EXPLICIT_COLOR_MAP: dict[str, str] = {
    "1F4E9C": "blue",     # C_V1 主向量 / 變換後
    "2F3E5C": "navy",     # C_V2 原基底 / 變換前
    "1A9E8F": "teal",     # C_T1 特徵空間 / 交集
    "6A4C93": "purple",   # C_T2 二級變換
    "D9480F": "orange",   # C_WARN 反例 / 錯誤
    "8FA3BF": "gray",     # C_AUX 輔助線
}

# 色差超過此閾值時,仍然替換,但寫入報告請人工確認
COLOR_DISTANCE_WARN = 120.0
# 兩色都夠鮮豔(飽和度高於此值)而色相相差超過 HUE_WARN 度時,也寫入報告
HUE_SATURATION_MIN = 0.25
HUE_WARN = 30.0


def parse_hex(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:  # RGBA → 忽略 alpha
        h = h[:6]
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def nearest_named(rgb):
    best, best_d = None, float("inf")
    for name, c in NAMED_COLORS.items():
        d = sum((a - b) ** 2 for a, b in zip(rgb, c)) ** 0.5
        if d < best_d:
            best, best_d = name, d
    return best, best_d


def hue_gap(rgb_a, rgb_b):
    """兩色都夠鮮豔時回傳色相差(度),否則回傳 None。"""
    ha, sa, _ = colorsys.rgb_to_hsv(*(x / 255 for x in rgb_a))
    hb, sb, _ = colorsys.rgb_to_hsv(*(x / 255 for x in rgb_b))
    if sa < HUE_SATURATION_MIN or sb < HUE_SATURATION_MIN:
        return None
    d = abs(ha - hb) * 360
    return round(min(d, 360 - d), 1)  # 取一位小數再比較,與報告顯示的值一致(避免 30.000000000000014 這類邊界誤報)


HEX_COLOR_RE = re.compile(
    r"\\(?P<cmd>textcolor|color)\s*\{\s*#(?P<hex>[0-9a-fA-F]{3,8})\s*\}"
)
HEX_COLOR_HTML_RE = re.compile(
    r"\\(?P<cmd>textcolor|color)\s*\[HTML\]\s*\{\s*(?P<hex>[0-9a-fA-F]{6})\s*\}"
)


def named_color(match):
    hexval = match["hex"].upper()
    rgb = parse_hex(hexval)
    if rgb is None:
        return None, {"type": "unparseable_hex_color", "value": hexval}
    explicit = EXPLICIT_COLOR_MAP.get(hexval)
    name, dist = (explicit, 0.0) if explicit else nearest_named(rgb)
    entry = {"hex": f"#{hexval}", "named": name, "distance": round(dist, 1)}
    if dist > COLOR_DISTANCE_WARN:
        return entry, {"type": "color_distance_large", **entry}
    gap = hue_gap(rgb, NAMED_COLORS[name]) if not explicit else None
    if gap is not None and gap > HUE_WARN:
        return entry, {"type": "color_hue_mismatch", **entry, "hue_gap": gap}
    return entry, None


# ---------------------------------------------------------------------------
# 2. LaTeX 命令替換表(可自行擴充)
# ---------------------------------------------------------------------------

# 每條規則都按完整命令名比對:命令名後面不能緊接英文字母(否則是別的命令)。
END = r"(?![A-Za-z])"
# (regex, replacement, label) — 順序重要:長命令在前。
COMMAND_SUBS = [
    (r"\\longleftrightarrow" + END, "⟷",                    r"\longleftrightarrow → ⟷"),
    (r"\\longrightarrow" + END,     "⟶",                    r"\longrightarrow → ⟶"),
    (r"\\Longrightarrow" + END,     "⟹",                    r"\Longrightarrow → ⟹"),
    (r"\\Longleftrightarrow" + END, "⟺",                    r"\Longleftrightarrow → ⟺"),
    (r"\\Uparrow" + END,            "↑",                    r"\Uparrow → ↑"),
    (r"\\Downarrow" + END,          "↓",                    r"\Downarrow → ↓"),
    (r"\\hbar" + END,               "ħ",                    r"\hbar → ħ"),
    (r"\\blacksquare" + END,        "■",                    r"\blacksquare → ■"),
    (r"\\iff" + END,                "⟺",                    r"\iff → ⟺"),
    (r"\\bmod" + END,               r"\\operatorname{mod}", r"\bmod → \operatorname{mod}"),
    (r"\\notin" + END,              "∉",                    r"\notin → ∉"),
    # {\sf T} 與 \sf T → \top
    (r"\{\\sf\s+T\}",               r"\\top",               r"{\sf T} → \top"),   # 要有空白:{\sfT} 是別的命令
    (r"\\sf\s+T" + END,             r"\\top",               r"\sf T → \top"),
    # Typst 不支援的樣式命令:直接移除
    (r"\\displaystyle" + END + r"[ \t]*", "",              r"移除 \displaystyle"),
    (r"\\scriptstyle" + END + r"[ \t]*",  "",              r"移除 \scriptstyle"),
]

COMMAND_PATTERNS = [(re.compile(pattern), replacement, label) for pattern, replacement, label in COMMAND_SUBS]
MATH_LABEL = re.compile(r"\\label\{([^}]+)\}")
ARROW = re.compile(r"\\xrightarrow" + END)
ARROW_RULE = r"\xrightarrow{...} → \overset{...}{⟶}"


class Changes:
    """只寫入可由解析位置逐字核對的原文範圍。"""

    def __init__(self, text, report):
        self.text = text
        self.report = report
        self.edits = []
        self.events = []
        self.reviews = []

    def review(self, view, kind, **fields):
        at = view.at()
        if at is not None:
            fields.setdefault("context", self.text[at:view.positions[-1] + 1]
                              if view.positions[-1] is not None else view.text)
            self.reviews.append((at, {"type": kind, **fields}))

    def patch(self, view, replacements):
        edits = []
        for start, stop, replacement in replacements:
            if start == stop:
                pivot = view.positions[start - 1]
                at = None if pivot is None else pivot + 1
                original = ""
            else:
                at = view.positions[start]
                original = view.text[start:stop]
            if (at is None or "\n" in original or self.text[at:at + len(original)] != original
                    or any(pos != at + i for i, pos in enumerate(view.positions[start:stop]))):
                self.review(view[start:stop] if start != stop else view, "ambiguous_source",
                            reason="替換範圍跨過原文換行、容器前綴或展開的 Tab")
                return False
            edits.append((at, at + len(original), replacement))
        self.edits.extend(edits)
        return True

    def finish(self, base, events):
        pieces, ends, deltas = [], [], []
        cursor, delta = 0, 0
        for start, stop, replacement in sorted(self.edits):
            if start < cursor:
                raise ValueError("替換範圍重疊")
            pieces.extend((self.text[cursor:start], replacement))
            cursor = stop
            delta += len(replacement) - (stop - start)
            ends.append(stop)
            deltas.append(delta)

        def position(at):
            index = bisect_right(ends, at)
            return base + at + (deltas[index - 1] if index else 0)

        events.extend((kind, value, position(at), context)
                      for at, kind, value, context in sorted(self.events, key=lambda item: item[0]))
        self.report["needs_review"].extend(
            {**item, "position": position(at)}
            for at, item in sorted(self.reviews, key=lambda entry: entry[0])
        )
        pieces.append(self.text[cursor:])
        return "".join(pieces)


def group_end(text, start):
    """掃描一組 LaTeX 參數，略過跳脫字元與 TeX 註解，並配對巢狀括號。"""
    stack = ["}" if text[start] == "{" else "]"]
    i = start + 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "%":
            end = text.find("\n", i)
            if end < 0:
                break
            i = end + 1
            continue
        if char == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
        elif char == "{" or (char == "[" and stack[-1] == "]"):
            stack.append("}" if char == "{" else "]")
        i += 1
    return None


def skip_argument_gap(text, start):
    while start < len(text):
        if text[start].isspace():
            start += 1
        elif text[start] == "%":
            end = text.find("\n", start)
            if end < 0:
                return len(text)
            start = end + 1
        else:
            break
    return start


def arrow_parts(text, command):
    start = skip_argument_gap(text, command.end())
    cursor = start
    while text[cursor:cursor + 1] == "[":
        cursor = skip_argument_gap(text, group_end(text, cursor) or len(text))
    if text[cursor:cursor + 1] != "{":
        return max(command.end(), cursor), None
    end = group_end(text, cursor)
    if end is None:
        return len(text), None
    extra = skip_argument_gap(text, end)
    if text[extra:extra + 1] == "[":
        while text[extra:extra + 1] == "[":
            end = group_end(text, extra) or len(text)
            extra = skip_argument_gap(text, end)
        return end, None
    argument = text[cursor + 1:end - 1]
    if (cursor != start or "%" in text[command.end():start] or re.search(r"[{}]", argument)
            or any(not escaped(argument, match.start()) for match in re.finditer("%", argument))):
        return end, None
    return end, cursor


def fix_math(view, changes, display):
    text = view.text
    counts = {}
    protected_until = 0
    for candidate in re.finditer(r"\\|%|\{(?=\\sf\b)", text):
        at = candidate.start()
        if at < protected_until or (text[at] in "\\%" and escaped(text, at)):
            continue
        if text[at] == "%":
            end = text.find("\n", at)
            protected_until = len(text) if end < 0 else end
            continue
        if arrow := ARROW.match(text, at):
            end, brace = arrow_parts(text, arrow)
            if brace is None:
                changes.review(view[at:end], "complex_xrightarrow")
                protected_until = end
            elif changes.patch(view, [(at, brace + 1, r"\overset{"), (end, end, "{⟶}")]):
                counts[ARROW_RULE] = counts.get(ARROW_RULE, 0) + 1
                protected_until = brace + 1
            else:
                protected_until = end
            continue
        color = HEX_COLOR_RE.match(text, at) or HEX_COLOR_HTML_RE.match(text, at)
        if color:
            entry, review = named_color(color)
            if entry:
                replacement = f"\\{color['cmd']}{{{entry['named']}}}"
                if not changes.patch(view, [(at, color.end(), replacement)]):
                    continue
                changes.report["color_replacements"].append(entry)
            if review:
                kind = review.pop("type")
                changes.review(view[at:color.end()], kind, **review)
            protected_until = color.end()
            continue
        if display and (definition := MATH_LABEL.match(text, at)):
            label = definition[1].strip()
            if valid_label(label) and view.at(at) is not None:
                changes.events.append((view.at(at), "def", label, ""))
            protected_until = definition.end()
            continue
        for pattern, replacement, name in COMMAND_PATTERNS:
            match = pattern.match(text, at)
            if match:
                if changes.patch(view, [(at, match.end(), match.expand(replacement))]):
                    counts[name] = counts.get(name, 0) + 1
                protected_until = match.end()
                break
    changes.report["command_replacements"].extend(
        {"rule": rule, "count": count} for rule, count in counts.items()
    )


def fix_markdown(text: str, report: dict, events: list, base: int = 0):
    changes = Changes(text, report)
    for region in regions(View.original(text)):
        at = region.at if region.at is not None else region.view.at()
        if region.kind in ("math", "display"):
            fix_math(region.view, changes, region.kind == "display")
        elif region.kind in ("ambiguous_source", "math_backticks"):
            changes.review(region.view, region.kind, **({"reason": region.value} if region.value else {}))
        elif at is not None:
            if region.kind == "rename":
                if not changes.patch(region.view, [(0, len(region.view.text), "label")]):
                    continue
                report["command_replacements"].append({
                    "rule": ":name: → :label:", "count": 1, "label_value": region.value,
                })
            kind = "ref" if region.kind == "ref" else "def"
            changes.events.append((at, kind, region.value, region.context))
    return changes.finish(base, events)


def check_ref_order(events: list, report: dict, origin: str = ""):
    """事件按原文次序排列，位置以修復後字元計算。"""
    first_def = {}
    for kind, label, pos, _ in events:
        if kind == "def":
            first_def.setdefault(label, pos)
    for kind, label, pos, context in events:
        if kind == "ref" and (label not in first_def or pos < first_def[label]):
            issue = "forward_reference" if label in first_def else "undefined_reference"
            report["needs_review"].append({
                "type": issue, "label": label, "position": pos, "origin": origin, "context": context,
            })
    report["needs_review"].sort(key=lambda item: item.get("position", -1))


def new_report():
    return {"color_replacements": [], "command_replacements": [], "needs_review": []}


def fix_notebook(notebook, report, origin=""):
    fixed_notebook = deepcopy(notebook)
    events, offset = [], 0
    for cell in fixed_notebook.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", "")
        joined = "".join(source) if isinstance(source, list) else source
        fixed = fix_markdown(joined, report, events, base=offset)
        offset += len(fixed) + 2
        if fixed != joined:
            cell["source"] = fixed.splitlines(keepends=True) if isinstance(source, list) else fixed
    check_ref_order(events, report, origin=origin)
    return fixed_notebook


def process_document(path, report):
    with path.open(encoding="utf-8", newline="") as stream:
        text = stream.read()
    if path.suffix.lower() == ".ipynb":
        notebook = json.loads(text)
        fixed = fix_notebook(notebook, report, origin=path.name)
        return text if fixed == notebook else json.dumps(fixed, ensure_ascii=False, indent=1) + "\n"
    events = []
    fixed = fix_markdown(text, report, events)
    check_ref_order(events, report, origin=path.name)
    return fixed


def summarize(report: dict) -> str:
    lines = ["=" * 60, "Typst 相容性修復報告", "=" * 60]
    agg = {}
    for r in report["command_replacements"]:
        agg[r["rule"]] = agg.get(r["rule"], 0) + r["count"]
    if agg:
        lines.append("\n[自動替換]")
        for rule, n in agg.items():
            lines.append(f"  {rule}  × {n}")
    if report["color_replacements"]:
        lines.append("\n[顏色映射]")
        seen = {}
        for c in report["color_replacements"]:
            key = (c["hex"], c["named"])
            seen[key] = seen.get(key, 0) + 1
        for (h, name), n in seen.items():
            lines.append(f"  {h} → {name}  × {n}")
    if report["needs_review"]:
        lines.append("\n[⚠ 需人工判斷 — 交由執行者處理]")
        for item in report["needs_review"]:
            t = item["type"]
            if t == "forward_reference":
                lines.append(f"  前向引用: `{item['label']}` 在定義之前被引用")
            elif t == "undefined_reference":
                lines.append(f"  未定義引用: `{item['label']}`")
            elif t == "complex_xrightarrow":
                lines.append(f"  複雜 \\xrightarrow: ...{item['context'][:60]}...")
            elif t == "math_backticks":
                lines.append(f"  公式內含反引號(位置 {item['position']}): {item['context']},請人工確認")
            elif t == "ambiguous_source":
                lines.append(f"  原文位置 {item['position']} 需確認：{item['reason']}｜{item['context'][:80]}")
            elif t == "color_distance_large":
                lines.append(
                    f"  色差較大: {item['hex']} → {item['named']} "
                    f"(距離 {item['distance']}),請確認")
            elif t == "color_hue_mismatch":
                lines.append(
                    f"  色相不符: {item['hex']} → {item['named']} "
                    f"(色相差 {item['hue_gap']} 度),請確認")
            else:
                lines.append(f"  {t}: {item}")
    else:
        lines.append("\n✓ 無需人工判斷的項目")
    return "\n".join(lines)


def path_identity(path):
    resolved = path.resolve()
    try:
        info = resolved.stat()
    except FileNotFoundError:
        return resolved, None
    return resolved, (info.st_dev, info.st_ino)


def validate_paths(sources, targets, report, in_place):
    by_path, by_inode = {}, {}
    entries = [(path, "輸入", i) for i, path in enumerate(sources)]
    entries.extend((path, "輸出", i) for i, path in enumerate(targets))
    if report is not None:
        entries.append((report, "報告", None))
    resolved_targets = []
    for path, role, i in entries:
        resolved, inode = path_identity(path)
        if role == "輸入":
            if path.suffix.lower() not in (".md", ".ipynb") or not resolved.is_file():
                raise ValueError(f"輸入必須是現存的 .md 或 .ipynb 檔案：{path}")
        elif not resolved.parent.is_dir() or (inode is not None and not resolved.is_file()):
            raise ValueError(f"{role}必須指向可存放檔案的現存目錄：{path}")

        seen = by_path.get(resolved) or by_inode.get(inode)
        if seen is not None and not (in_place and seen == ("輸入", i) and role == "輸出"):
            raise ValueError(f"{role}路徑與其他輸入、輸出或報告重合：{path}")
        by_path[resolved] = (role, i)
        if inode is not None:
            by_inode[inode] = (role, i)
        if role != "輸入":
            resolved_targets.append(resolved)
    return resolved_targets


def write_atomic(path, content):
    staged = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=".fix-typst-", suffix=".tmp", delete=False,
        ) as stream:
            staged = Path(stream.name)
            stream.write(content)
        os.replace(staged, path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main():
    # 終端機不是 UTF-8 時(例如 Windows 的舊代碼頁),摘要裡的 ⟶、⟺ 不能讓程式中斷
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", metavar="input", help="一個或多個 .md 或 .ipynb 檔案")
    ap.add_argument("-o", "--output", help="輸出路徑(僅限單一輸入檔案;預設加 .fixed 後綴)")
    ap.add_argument("--in-place", action="store_true", help="原地覆寫")
    ap.add_argument("--report", help="將 JSON 報告寫入此路徑")
    args = ap.parse_args()

    if args.output and args.in_place:
        ap.error("-o/--output 與 --in-place 不可同時使用")
    if args.output and len(args.inputs) > 1:
        ap.error("-o/--output 僅支援單一輸入檔案;多檔模式請省略 -o 或改用 --in-place")

    sources = [Path(path) for path in args.inputs]
    if args.in_place:
        targets = sources
    elif args.output:
        targets = [Path(args.output)]
    else:
        targets = [src.with_name(src.stem + ".fixed" + src.suffix) for src in sources]
    report_path = Path(args.report) if args.report else None
    try:
        resolved = validate_paths(sources, targets, report_path, args.in_place)
    except (ValueError, OSError, RuntimeError) as error:
        ap.error(str(error))

    reports_by_file = {}
    for src, dst, real_dst in zip(sources, targets, resolved):
        report = new_report()
        try:
            out_text = process_document(src, report)
            write_atomic(real_dst, out_text)
        except (ValueError, OSError, TypeError) as error:
            ap.exit(1, f"處理失敗（{src} → {dst}）：{error}\n")
        reports_by_file[str(src)] = report
        print(summarize(report))
        print(f"\n輸出：{dst}")

    if report_path is not None:
        payload = (next(iter(reports_by_file.values())) if len(sources) == 1
                   else {"files": reports_by_file})
        try:
            write_atomic(resolved[-1], json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as error:
            ap.exit(1, f"寫入報告失敗（{report_path}）：{error}\n")


if __name__ == "__main__":
    main()
