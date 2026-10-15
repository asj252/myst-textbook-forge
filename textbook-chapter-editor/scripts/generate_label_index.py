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

# ---------------------------------------------------------------------------
# 正規表達式
# ---------------------------------------------------------------------------

# 圍欄開頭：``` / ~~~ / :::（後面可帶 {directive} 與標題）
RE_FENCE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,}|:{3,})\s*(?P<info>.*?)\s*$")
RE_DIRECTIVE_INFO = re.compile(r"^\{(?P<name>[a-zA-Z][\w:-]*)\}\s*(?P<title>.*)$")
CODE_DIRECTIVES = {"code-cell", "code", "code-block", "sourcecode"}

# :label: xxx
RE_LABEL = re.compile(r"^\s*:label:\s*(\S+)\s*$")
# directive 的其他選項行
RE_OPTION = re.compile(r"^\s*:[A-Za-z][\w-]*:(\s|$)")

# heading target:  (sec-foo)=
RE_TARGET = re.compile(r"^\(([A-Za-z0-9_:.-]+)\)=\s*$")

# 章節標題：#, ##, ### ...
RE_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")  # 可以縮排 0–3 格、可以是空標題、可以有結尾的 #

# $$ ... $$ (eq-label)  — 行尾括號式方程 label
RE_DOLLAR_EQ_LABEL = re.compile(r"\$\$\s*\(([A-Za-z0-9_:.-]+)\)\s*$")

# 角色的開頭 {name}，後面緊接一段反引號
RE_ROLE_HEAD = re.compile(r"\{[A-Za-z][\w:-]*\}(?=`)")
# 縮排程式碼區塊：前一行是空行（或已在縮排區塊裡）、本行縮排至少四格或一個 tab，而且不在列表裡
RE_INDENTED = re.compile(r"^(?: {4}|\t)")
RE_LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)")
RE_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")  # 分隔線
RE_BLOCK_START = re.compile(r"^ {0,3}(?:`{3,}[^`]*$|~{3,}|:{3,}|#{1,6}(?:\s|$)|>|\$\$|\([^()\s]+\)=\s*$|([-*_])(?:[ \t]*\1){2,}[ \t]*$)")  # 能打斷段落的區塊開頭
RE_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")  # 段落下一行的 === 或 ---：把段落變成標題
# 引用區塊的行首標記（> ），去掉後再按正文處理
RE_BQ = re.compile(r"^(?: {0,3}> ?)+")
# 列表標記後緊接 Tab（行首可以有空白、引用標記與外層列表標記）
RE_CONTAINER = re.compile(r"^(?:[ \t]*(?:>|[-*+](?=[ \t]|$)|\d{1,9}[.)](?=[ \t]|$)))*[ \t]*")  # 行首的引用標記、列表標記與空白
RE_MARKER_TAB = re.compile(r"^[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)*?(?:[-*+]|\d{1,9}[.)])\t")

# 引用：{prf:ref}`label`、{ref}`label`、{numref}`label`、{eq}`label`
# 亦支援 {ref}`文字 <label>` 形式
RE_REF = re.compile(
    r"\{(prf:ref|ref|numref|eq)\}`(?:[^`<>]*<([A-Za-z0-9_:.-]+)>|([A-Za-z0-9_:.-]+))`"
)

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


def escaped(text, i):
    """text[i] 前面有奇數個反斜線 = 被轉義。"""
    n = 0
    while i - 1 - n >= 0 and text[i - 1 - n] == "\\":
        n += 1
    return n % 2 == 1


def strip_inline_code(line):
    """把行內程式碼換成空白，保留角色（引用寫在角色裡）；轉義的 \\{ 與 \\` 不算開頭。
    反引號段按長度配對：同樣長度的一段反引號才能結束它。同一行內處理；跨行的行內程式碼是已知限制。"""
    out, i, n = [], 0, len(line)
    while i < n:
        ch = line[i]
        if ch in "{`" and escaped(line, i):
            out.append(ch)
            i += 1
            continue
        if ch == "{":
            m = RE_ROLE_HEAD.match(line, i)
            if m:
                j = m.end()
                k = j
                while k < n and line[k] == "`":
                    k += 1
                run = k - j
                end = line.find("`" * run, k)
                while end != -1 and (end + run < n and line[end + run] == "`" or end > 0 and line[end - 1] == "`"):
                    end = line.find("`" * run, end + 1)
                if end != -1:
                    out.append(line[i:end + run])  # 角色原樣保留
                    i = end + run
                    continue
            out.append(ch)
            i += 1
            continue
        if ch == "`":
            k = i
            while k < n and line[k] == "`":
                k += 1
            run = k - i
            end = line.find("`" * run, k)
            while end != -1 and (end + run < n and line[end + run] == "`" or line[end - 1] == "`"):
                end = line.find("`" * run, end + 1)
            if end != -1:
                out.append(" " * (end + run - i))  # 行內程式碼換成空白
                i = end + run
                continue
            out.append(line[i:k])  # 找不到配對：當普通文字
            i = k
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_cols(s, cols):
    """從行首扣掉 cols 欄的空白（Tab 以 4 欄定位）；跨過界線的 Tab 換成剩下欄數的空格，其餘 Tab 原樣保留。"""
    col, i = 0, 0
    while i < len(s) and col < cols and s[i] in " \t":
        w = 4 - col % 4 if s[i] == "\t" else 1
        if col + w > cols:
            return " " * (col + w - cols) + s[i + 1:]
        col += w
        i += 1
    return s[i:]


def section_of(title):
    sec = re.search(r"§?\s*(\d+(?:\.\d+)*)", title)
    if sec:
        return f"§{sec.group(1)}"
    return title if len(title) <= 40 else title[:40]


# ---------------------------------------------------------------------------
# 掃描單一文字內容（一份 .md 全文或一個 markdown cell）
# ---------------------------------------------------------------------------

def scan_text(lines, source, labels, refs, start_section="", pending_anchors=None, uncertain=None, where=None, line_base=0):
    """逐行掃描，收集 label 與 reference。

    labels: list of dict(label, kind, title, section, source)
    refs:   list of dict(label, source, section)
    pending_anchors：寫在標題之前、還在等下一個標題的錨點；ipynb 跨 cell 傳下去，檔案結束時再歸到當時的章節。
    uncertain：本腳本切分不一定準的位置（引用區塊裡的列表、圍欄、Tab 或縮排內容），收進 dict(where, line, text)；
    where 是報告裡顯示的位置（預設為 source）。
    回傳掃描結束時的 current_section（供 ipynb 跨 cell 延續）。
    """
    current_section = start_section
    stack = []                # 開著的圍欄：(圍欄字元, 長度, 是否程式碼, 開在第幾層列表裡, 是否開在引用區塊裡)
    pending_directive = None  # (kind, title)：剛開的 directive，等它的選項行
    carry = pending_anchors is not None
    if pending_anchors is None:
        pending_anchors = []  # 寫在標題之前的 (sec-x)=，等下一個標題

    def add_refs(text):
        masked = strip_inline_code(text)
        for rm in RE_REF.finditer(masked):
            if not escaped(masked, rm.start()):  # \{ref}`x` 是轉義，不是引用
                refs.append(dict(label=rm.group(2) or rm.group(3), source=source,
                                 section=current_section))

    def flush_anchors():
        for lab in pending_anchors:
            labels.append(dict(label=lab, kind="標題錨點", title=current_section,
                               section=current_section, source=source))
        pending_anchors.clear()

    prev_blank, in_indented, lists = True, False, []  # lists：所在各層列表項目內容的起始欄（由外到內）
    marks, in_para = [], False  # marks：各層列表標記的（欄位, 種類）；in_para：上一行是段落正文
    last_bq = False  # 上一行在引用區塊裡
    empty_item = False  # 上一行是只有標記、沒有內容的列表項目
    skip_to = 0  # directive 的內文由遞迴掃描處理，主迴圈跳到這一行之後
    for ln, line in enumerate(lines, 1):
        if ln <= skip_to:
            continue
        raw = line
        line = line.expandtabs(4)  # 先按原始欄位把 Tab 展開（4 欄定位），引用標記與列表標記後的 Tab 才算得對
        in_bq = bool(RE_BQ.match(line))
        qcol = len(line) - len(line.lstrip(" "))  # 引用標記所在的欄（只在 in_bq 時有意義）
        # 引用區塊外、列表裡開的圍欄：按原始縮排看列表項目是否已經結束（結束了圍欄也跟著結束，這一行再照一般規則處理）
        while line.strip() and stack and stack[-1][3] and not stack[-1][4] and (
                stack[-1][3] > len(lists) or qcol < lists[stack[-1][3] - 1]):
            stack.pop()
            pending_directive = None
        # markdown-it 的引用區塊延續行：> 前面縮排 4 格以上也算（開頭那一行不算）；與 CommonMark 不同，列為需要人工確認
        deep_quote = False
        if not in_bq and last_bq and re.match(r"^ {4,}>", line) and not (stack and stack[-1][2] and not stack[-1][4]):
            in_bq = deep_quote = True
            line = re.sub(r"^ *> ?", "", line)
        if stack and stack[-1][2]:  # 在程式碼圍欄裡
            if stack[-1][4] and not in_bq:
                stack.pop()  # 引用區塊裡開的圍欄：這一行已不在引用區塊裡（含空行），引用區塊結束，圍欄也跟著結束
            elif not stack[-1][4]:
                in_bq = False  # 引用區塊外開的圍欄：行首的 > 是程式碼內容，不去掉
        if in_bq:
            line = RE_BQ.sub("", line)  # 引用區塊：去掉行首的 > 再按正文處理（其中的圍欄也照常識別）
        # 本腳本的切分可能與 MyST 不同的寫法（已知限制），記下來請人工確認：
        # A 引用區塊裡的列表、圍欄、Tab 與縮排內容；B 列表裡的引用區塊；C 列表標記後緊接 Tab；D 空的列表項目（見下）
        lead = raw[:len(raw) - len(raw.lstrip(" \t>"))]  # 行首的空白與引用標記（展開 Tab 之前）
        flag_a = deep_quote or in_bq and bool(raw.strip()) and ("\t" in lead or (bool(RE_LIST_ITEM.match(line)) and not RE_HR.match(line)) or bool(RE_FENCE.match(line))
                                                   or len(line) - len(line.lstrip(" ")) >= 4)
        # A 也包括引用區塊裡段落的延續行：上一行是引用區塊裡的段落正文，這一行沒有 >（Markdown 仍算在引用區塊裡）
        # （能結束引用段落的區塊開頭——標題、分隔線、圍欄、列表項目——不是延續行，不列）
        flag_a = flag_a or (last_bq and in_para and not in_bq and bool(raw.strip())
                            and not RE_BLOCK_START.match(line) and not RE_LIST_ITEM.match(line))
        quote_starts = in_bq and not last_bq  # 這一行開始一個新的引用區塊（是區塊開頭，不是列表段落的延續行）
        quote_ends = last_bq and not in_bq  # 上一行在引用區塊裡、這一行不在：引用裡的段落不再限制這一行（列表標記可以直接開始列表）
        last_bq = in_bq
        flag_bc = bool(raw.strip()) and (">" in RE_CONTAINER.match(line).group(0) or bool(RE_MARKER_TAB.match(raw))
                                          or (in_bq and bool(lists) and qcol >= lists[0]))  # B 也包括縮排到列表內容的引用區塊

        def mark(also_bc=True):
            if uncertain is not None and (flag_a or (also_bc and flag_bc)):
                uncertain.append(dict(where=where or source, line=ln + line_base, text=raw.strip()))

        indent = len(line) - len(line.lstrip(" "))
        if quote_starts and lists:  # 新的引用區塊開在列表內容之前（含空的 >）：那些列表項目結束
            while lists and qcol < lists[-1]:
                lists.pop()
                marks.pop()
            in_para = False
            empty_item = False
        if empty_item and not line.strip():
            lists.pop()  # 空的列表項目後面隔了空行：這個項目就結束了（項目最多只能以一個空行開頭）
            marks.pop()
        empty_item = False
        # 列表裡開的圍欄：縮排回到該層列表內容之前（列表項目結束），圍欄也跟著結束
        while line.strip() and stack and stack[-1][3] and (stack[-1][3] > len(lists) or indent < lists[stack[-1][3] - 1]):
            stack.pop()
            pending_directive = None
        in_code = any(e[2] for e in stack)
        item_first = False  # 這一行是列表項目的第一行（標記所在的行）
        indented_first = False
        was_para, in_para = in_para, False  # 上一行是不是段落正文（列表能不能打斷它、縮排程式碼能不能開始，都看這個）
        para_limits = was_para and not quote_ends  # 段落對列表標記、setext 底線的限制（引用區塊剛結束時不適用）
        interrupted = False  # 這一行是上一段的延續正文（不能打斷段落的列表標記）
        if not in_code and line.strip():
            new_lists, new_marks, popped = list(lists), list(marks), []
            while new_lists and indent < new_lists[-1]:
                new_lists.pop()  # 縮排少於這層列表內容：離開這層列表
                popped.append(new_marks.pop())
            # 從目前所在的內容起點找列表標記；同一行可以有好幾層（如「- - ```」），一層一層往內找
            start = new_lists[-1] if new_lists else 0
            first = True
            while True:
                seg = line[start:]
                if RE_HR.match(seg):
                    break  # 分隔線（如「- - -」「* * *」）不是列表
                if first and para_limits and not popped and RE_SETEXT.match(seg):
                    break  # 段落下一行單獨的「-」「---」：是 setext 標題的底線，不是空的列表項目
                lm_ = RE_LIST_ITEM.match(seg)
                if not lm_:
                    break
                # 內容起點 = 標記末尾 + 後面的空格數（1–4 格；5 格以上或標記後就換行時算 1 格），與 CommonMark 相同
                marker = start + len(lm_.group(0).rstrip())
                spaces = len(line) - len(line[marker:].lstrip(" ")) - marker
                rest = line[marker:].strip()
                tok = lm_.group(0).strip()
                kind = (start + len(seg) - len(seg.lstrip(" ")), tok if tok in "-*+" else tok[-1])
                # 新列表的第一個項目打斷同一層的段落時：有序的必須從 1 開始、不能是空項目
                # （縮排退回外層的行不受限：它本來就結束了那個段落所在的列表項目；同一列表的下一個項目也是這樣）
                if first and para_limits and not popped and ((tok[-1] in ".)" and int(tok[:-1]) != 1) or not rest):
                    interrupted = True
                    break
                new_lists.append(marker + (spaces if 1 <= spaces <= 4 and rest else 1))
                new_marks.append(kind)
                item_first, first = True, False
                if spaces >= 5 and rest:  # 標記後 5 格以上：項目第一行本身就是縮排程式碼
                    indented_first = True
                    break
                start = new_lists[-1]
            # 段落的延續行（lazy continuation）：上一行是段落正文、這一行不是任何區塊的開頭，縮排少也仍在原來的列表裡
            # 縮排比段落所在的列表內容少：相對那一層永遠不到 4 格，所以去掉全部縮排再看是不是區塊開頭（與 markdown-it 相同）
            if not interrupted and first and popped and was_para and not quote_starts \
                    and not RE_BLOCK_START.match(line.lstrip(" ")):
                interrupted = True
            if interrupted:
                in_para = True  # 這一行是上一段的延續正文，列表不變
            else:
                if popped:
                    was_para = False  # 離開了段落所在的列表項目：那個段落已經結束（之後的縮排程式碼等可以直接開始）
                lists[:], marks[:] = new_lists, new_marks
        if indented_first:
            mark(False)
            in_indented, prev_blank = True, False
            continue
        # 列表裡的行從最內層列表內容的起點算（項目第一行的圍欄可以直接接在標記後面）
        base = lists[-1] if lists else 0
        # 縮排程式碼區塊：比所在位置（正文或列表內容）再多縮排四格以上，上一行不是段落正文（或已在縮排區塊裡）；整段跳過
        if not in_code and pending_directive is None and line.strip() and indent >= base + 4 \
                and (not was_para or in_indented):
            mark(False)  # 已確定是程式碼示例：只有引用區塊裡的才要人工確認
            in_indented, prev_blank = True, False
            continue
        if not in_code:
            mark()
        if line.strip():
            in_indented = False
        # 只有標記、沒有內容的列表項目行（如單獨一個「-」）後面沒有段落，下一行的縮排內容可以直接成為程式碼區塊
        empty_item = item_first and not line[base:].strip()
        if empty_item and uncertain is not None and not (flag_a or flag_bc):  # D 空的列表項目（標記後沒有內容）
            uncertain.append(dict(where=where or source, line=ln + line_base, text=raw.strip()))
        prev_blank = not line.strip() or empty_item
        # 分隔線，或段落下一行的 ===／---（把段落變成標題）：都結束段落
        if not in_code and not interrupted and line.strip() and (
                RE_HR.match(line[base:]) or (was_para and RE_SETEXT.match(line[base:]))):
            continue
        m = None if interrupted else RE_FENCE.match(line[base:])  # 列表裡的圍欄（含結尾）從列表內容的欄位算起
        if m and m.group("fence")[0] == "`" and "`" in m.group("info"):
            m = None  # 反引號圍欄的 info 不能含反引號（那是行內程式碼，不是圍欄）
        if m:
            fence, info = m.group("fence"), m.group("info")
            ch, n = fence[0], len(fence)
            # 結尾圍欄：與最內層開著的同字元、長度不少於它、後面沒有內容，而且在同一層列表裡
            # （directive 內文裡更深一層的列表項目開頭的 ``` 是新的圍欄，不是 directive 的結尾）
            if stack and not info and stack[-1][0] == ch and n >= stack[-1][1] and len(lists) <= stack[-1][3]:
                stack.pop()
                pending_directive = None
                continue
            if in_code:
                continue
            d = RE_DIRECTIVE_INFO.match(info)
            # 沒有 directive 名稱的冒號圍欄（單獨的 :::）與 MyST 的 colon_fence 相同，當成程式碼圍欄
            is_code = d is None or d.group("name") in CODE_DIRECTIVES
            if is_code:
                stack.append((ch, n, is_code, len(lists), in_bq))
                continue
            # 一般 directive：與 MyST 相同，先找出它的範圍（同一層容器裡第一個相配的結尾圍欄，或容器先結束），
            # 開頭的選項行收 label，其餘內文當成一份獨立的 Markdown 遞迴掃描（內文裡沒寫結尾的圍欄不會吞掉外面的正文）
            flush_anchors()
            name, title = d.group("name"), d.group("title")
            add_refs(title)  # directive 標題裡的引用也要收
            content, k, explicit = [], ln, False
            fi = len(line[base:]) - len(line[base:].lstrip(" "))  # 開頭圍欄本身的縮排（0–3 格）：內文每行最多也扣掉這麼多
            while k < len(lines):
                r = lines[k].expandtabs(4)
                if in_bq:
                    if not RE_BQ.match(r):
                        break  # 引用區塊結束：directive 跟著結束
                    r = RE_BQ.sub("", r)
                if r.strip() and len(r) - len(r.lstrip(" ")) < base:
                    break  # 列表項目結束：directive 跟著結束
                r1 = r[base:] if not r[:base].strip() else r.lstrip(" ")  # 從容器內容欄算起（結尾圍欄的縮排按這個算）
                # 內文：與 markdown-it 相同，從原文（保留 Tab）扣掉容器內容欄與開頭圍欄本身的縮排，剩下的 Tab 留給遞迴掃描
                src = RE_BQ.sub("", lines[k]) if in_bq else lines[k]
                r2 = strip_cols(src, base + fi)
                cm = RE_FENCE.match(r1)
                if cm and not cm.group("info") and cm.group("fence")[0] == ch and len(cm.group("fence")) >= n \
                        and len(r1) - len(r1.lstrip(" ")) <= 3:
                    explicit = True
                    break
                content.append(r2)
                k += 1
            kind = DIRECTIVE_TYPE_NAMES.get(name, name or "其他")
            o = 0
            if content and content[0].strip() == "---":  # YAML 形式的選項
                e = next((x for x in range(1, len(content)) if content[x].strip() == "---"), None)
                if e is not None:
                    for x in content[1:e]:
                        ym = re.match(r"^\s*label:\s*(\S+)\s*$", x)
                        if ym:
                            labels.append(dict(label=ym.group(1), kind=kind, title=title,
                                               section=current_section, source=source))
                    o = e + 1
            while o < len(content) and RE_OPTION.match(content[o]):
                lm = RE_LABEL.match(content[o])
                if lm:
                    labels.append(dict(label=lm.group(1), kind=kind, title=title,
                                       section=current_section, source=source))
                o += 1
            current_section = scan_text(content[o:], source, labels, refs, current_section, pending_anchors,
                                        uncertain, where, line_base + ln + o)
            skip_to = k + 1 if explicit else k  # 跳過 directive 的內文與結尾（容器先結束時，結束的那一行照常處理）
            in_para = False
            continue
        if in_code:
            continue

        # directive 開頭緊接的選項行
        if pending_directive is not None:
            lm = RE_LABEL.match(line)
            if lm:
                kind_raw, title = pending_directive
                kind = DIRECTIVE_TYPE_NAMES.get(kind_raw, kind_raw or "其他")
                labels.append(dict(label=lm.group(1), kind=kind, title=title,
                                   section=current_section, source=source))
                continue
            if RE_OPTION.match(line):
                continue
            pending_directive = None

        # 章節標題追蹤；寫在它之前的錨點歸到它
        hm = None if interrupted else RE_HEADING.match(line[base:])  # 列表項目裡的標題從內容欄算起
        if hm:
            title = hm.group(2) or ""
            if title:  # 空標題（單獨一個 #）不改變目前的章節
                current_section = section_of(title)
            flush_anchors()
            add_refs(title)
            continue

        # heading target  (label)=
        tm = RE_TARGET.match(line)
        if tm:
            pending_anchors.append(tm.group(1))
            continue
        if line.strip():
            flush_anchors()  # 錨點後面不是標題：歸到目前的章節

        # $$ ... $$ (eq-label)
        em = RE_DOLLAR_EQ_LABEL.search(strip_inline_code(line))
        if em:
            labels.append(dict(label=em.group(1), kind="方程", title="",
                               section=current_section, source=source))

        in_para = bool(line[base:].strip()) or interrupted  # 只有列表標記、沒有內容的行不算段落
        add_refs(line)

    if not carry:
        flush_anchors()
    return current_section


# ---------------------------------------------------------------------------
# 檔案層級掃描
# ---------------------------------------------------------------------------

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
        out.append("引用區塊（`>`）裡的列表、程式碼圍欄、Tab、縮排內容與沒有 > 的延續行，列表裡的引用區塊、空的列表項目（標記後沒有內容），以及列表標記後緊接 Tab 的寫法，本腳本的切分可能與 MyST 不同："
                   "其中與其後的 label、引用可能漏收或誤收。請對照這些位置確認上面的結果。\n")
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
        print(f"⚠️ 有 {len(uncertain)} 處引用區塊或列表裡的特殊寫法（列表、圍欄、Tab、縮排內容、空的列表項目），結果可能不準，"
              f"請看報告末尾「需要人工確認的位置」", file=sys.stderr)


if __name__ == "__main__":
    main()
