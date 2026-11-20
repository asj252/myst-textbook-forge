"""用 MyST token 確認區段，在原始字元座標上記錄位置。"""

from copy import copy
from dataclasses import dataclass
import re

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from mdit_py_plugins.colon_fence import colon_fence_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.myst_blocks import myst_block_plugin
from mdit_py_plugins.myst_role import myst_role_plugin
import yaml


DIRECTIVE = re.compile(r"\{([a-zA-Z][\w:-]*)\}(?=\s|$)")
CODE = {
    "code-cell", "code", "code-block", "sourcecode", "literalinclude", "mermaid",
    "raw", "csv-table", "toctree", "eval-rst", "jupyter-execute", "ipython",
}
BODY = {
    "note", "admonition", "attention", "caution", "danger", "error", "hint",
    "important", "seealso", "tip", "warning", "exercise", "solution", "figure",
    "table", "list-table", "proof", "theorem", "definition", "example", "lemma",
    "proposition", "corollary", "property", "axiom", "algorithm", "remark",
    "conjecture", "prf:proof", "prf:theorem", "prf:definition", "prf:example",
    "prf:lemma", "prf:proposition", "prf:corollary", "prf:property", "prf:axiom",
    "prf:algorithm", "prf:remark", "prf:conjecture", "dropdown", "div",
    "tab-set", "tab-item", "margin", "sidebar", "topic", "image", "math",
}
REF_ROLES = {"ref", "numref", "eq", "prf:ref", "doc"}
REF_TARGET = re.compile(r"^(?:[^`<]*<)?([^`>]+)>?$")
ANCHOR = re.compile(r"\(([^)\s]+)\)=[ \t]*$")
OPTION = re.compile(r"([ \t]*):([a-zA-Z][\w-]*):(?=[ \t]|$)([^\n]*)")
DISPLAY_END = re.compile(r"(?<!\$)\$\$(?!\$)(?:[ \t]*\(([^)\s]+)\))?[ \t]*$")
ROLE = re.compile(r"\{([a-zA-Z0-9_+:\-]+)\}(`+)(?!`)")
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)

MATH_COMMENT_START = re.compile(r"<!--|%")


def escaped(text, at):
    left = at
    while left and text[left - 1] == "\\":
        left -= 1
    return (at - left) % 2 == 1


def math_comments(text):
    """依原文順序產生 HTML 註解與未跳脫的 TeX 註解起點。"""
    cursor = 0
    while marker := MATH_COMMENT_START.search(text, cursor):
        cursor = marker.end()
        if marker[0] == "<!--":
            comment = COMMENT.match(text, marker.start())
            yield comment
            cursor = comment.end()
        elif not escaped(text, marker.start()):
            yield marker
            end = text.find("\n", cursor)
            if end < 0:
                break
            cursor = end + 1


@dataclass(frozen=True)
class View:
    text: str
    positions: tuple

    @classmethod
    def original(cls, text):
        chars, positions = [], []
        for match in re.finditer(r"\r\n|[\s\S]", text):
            char = match[0]
            chars.append("\n" if char.startswith("\r") else char)
            positions.append(match.start())
        return cls("".join(chars), tuple(positions))

    def __getitem__(self, key):
        return View(self.text[key], self.positions[key])

    def strip(self):
        return self[len(self.text) - len(self.text.lstrip()):len(self.text.rstrip())]

    def lines(self):
        return [self[m.start():m.end()] for m in re.finditer(r"[^\n]*\n|[^\n]+$", self.text)]

    def at(self, index=0):
        return next((self.positions[i] for i in range(index, len(self.positions))
                     if self.positions[i] is not None), None)


def join(views):
    return View("".join(view.text for view in views), tuple(pos for view in views for pos in view.positions))


class MappedBlock(StateBlock):
    """在原規則讀取正文時記住參數，依原來的 Tab 規則核對來源。"""

    def getLines(self, begin, end, indent, keepLastLF):
        text = super().getLines(begin, end, indent, keepLastLF)
        self.last_read = (begin, end, indent, keepLastLF, text)
        return text

    def mapped_lines(self, begin, end, indent, keep_lf):
        source = self.env["source_view"]
        rows = []
        for row in range(begin, end):
            start = first = self.bMarks[row]
            stop = self.eMarks[row] + (row + 1 < end or keep_lf)
            width = 0
            while first < min(stop, len(self.src)) and width < indent:
                char = self.src[first]
                if char == "\t":
                    width += 4 - (width + self.bsCount[row]) % 4
                elif char == " " or first - start < self.tShift[row]:
                    width += 1
                else:
                    break
                first += 1
            pad = max(0, width - indent)
            rows.extend((View(" " * pad, (None,) * pad), source[first:stop]))
        return join(rows)

    def line_view(self, row):
        start = self.bMarks[row] + self.tShift[row]
        return self.env["source_view"][start:self.eMarks[row]]


def table_views(line):
    line = line.strip()
    bounds = [0, *(m.start() + 1 for m in re.finditer(r"(?<!\\)\|", line.text)), len(line.text) + 1]
    cells = [line[a:b - 1] for a, b in zip(bounds, bounds[1:])]
    if cells and not cells[0].text:
        cells.pop(0)
    if cells and not cells[-1].text:
        cells.pop()
    for cell in cells:
        # 表格規則會吃掉跳脫豎線的反斜線，其他字元的來源照常保留。
        keep = [i for i in range(len(cell.text)) if cell.text[i:i + 2] != r"\|"]
        yield View("".join(cell.text[i] for i in keep), tuple(cell.positions[i] for i in keep)).strip()


def comment_block(rule):
    """保護同一 HTML 區塊尾行接續開始的註解。"""
    def wrapped(state, first, last, silent):
        matched = rule(state, first, last, silent)
        if silent or not matched or not state.src.startswith("<!--", state.bMarks[first] + state.tShift[first]):
            return matched
        token = state.tokens[-1]
        row = state.line - 1
        cursor = token.content.find("-->")
        if cursor < 0 or "<!--" not in token.content[cursor + 3:]:
            return matched
        source = state.src
        last = min(last, state.lineMax)
        end = next((line for line in range(state.line, last)
                    if not state.isEmpty(line) and state.sCount[line] < state.blkIndent), last)
        limit = state.eMarks[end - 1]
        cursor = state.bMarks[first] + state.tShift[first]
        while True:
            closing = source.find("-->", cursor + 4, limit)
            if closing < 0:
                row = end - 1
                break
            while state.eMarks[row] < closing + 3:
                row += 1
            cursor = source.find("<!--", closing + 3, state.eMarks[row])
            if cursor < 0:
                break
        state.line = row + 1
        token.map[1] = state.line
        token.content = state.getLines(first, state.line, state.blkIndent, True)
        return matched
    return wrapped


def directive_fence(rule, name):
    """圍欄插件會把 HTML 註解內同長的標記當成結尾。試讀正文後核對該邊界。"""
    probe = markup_parser()

    def wrapped(state, first, last, silent):
        if name == "colon_fence" and not re.match(r":{3,}[ \t]*\{", state.line_view(first).text):
            return False
        if silent:
            return rule(state, first, last, silent)
        index = len(state.tokens)
        matched = rule(state, first, last, silent)
        if not matched:
            return matched
        token = state.tokens[-1]
        directive = DIRECTIVE.match(token.info.strip())
        if not directive or directive[1].split(":", 1)[0] in CODE or token.markup[0] not in "`:":
            return matched
        original = state.src
        try:
            while True:
                begin, close, indent, keep_lf, _ = state.last_read
                if close >= state.line:
                    break
                body = state.mapped_lines(begin, close, indent, keep_lf)
                if directive[1] == "math":
                    in_comment = any(comment[0] != "%" and not comment[0].endswith("-->")
                                     for comment in math_comments(body.text))
                else:
                    in_comment = has_open_comment(probe, body.text, close - begin)
                if not in_comment:
                    break
                start = state.bMarks[close] + state.tShift[close]
                stop = start + len(token.markup)
                state.src = state.src[:start] + ("_" * (stop - start)) + state.src[stop:]
                del state.tokens[index:]
                rule(state, first, last, silent)
                token = state.tokens[-1]
        finally:
            if state.src != original:
                state.src = original
                begin, close, indent, keep_lf, _ = state.last_read
                token.content = state.getLines(begin, close, indent, keep_lf)
        return matched
    return wrapped


def has_open_comment(probe, source, line_count):
    if "<!--" not in source:
        return False
    for token in probe.parse(source):
        if (token.type == "html_block" and token.map[1] == line_count
                and token.content.lstrip().startswith("<!--")
                and any(not match[0].endswith("-->") for match in COMMENT.finditer(token.content))):
            return True
        if token.type == "inline" and token.map[1] == line_count:
            for child in token.children:
                if child.type == "html_inline" and "span" in child.meta:
                    fragment = token.content[slice(*child.meta["span"])]
                    if fragment.startswith("<!--") and not fragment.endswith("-->"):
                        return True
    return False


def ends_in_tex_comment(body):
    line_start = body.rfind("\n") + 1
    return "%" in body[line_start:] and any(
        comment[0] == "%" and comment.start() >= line_start for comment in math_comments(body)
    )


def display_block(rule):
    """讓區塊插件跳過 TeX 註解中的關閉美元，保留原文座標。"""
    def wrapped(state, first, last, silent):
        original = state.src
        index, line = len(state.tokens), state.line
        begin = state.bMarks[first] + state.tShift[first] + 2
        try:
            while rule(state, first, last, silent):
                token = state.tokens[-1]
                end = begin + len(token.content)
                body = original[begin:end]
                if not ends_in_tex_comment(body):
                    token.content = body
                    return True
                state.src = state.src[:end] + "__" + state.src[end + 2:]
                del state.tokens[index:]
                state.line = line
            return False
        finally:
            state.src = original
    return wrapped


def paragraph_comment(rule):
    def wrapped(state, first, last, silent):
        rows = getattr(state, "tex_comment_rows", ())
        if silent and (rows is None or first in rows):
            return False
        return rule(state, first, last, silent)
    return wrapped


def display_paragraph(rule, parse_inline):
    """只在已確認的雙美元正文內，略過 MyST 行註解的段落中斷。"""
    def wrapped(state, first, last, silent):
        index, line = len(state.tokens), state.line
        matched = rule(state, first, last, silent)
        if not matched or silent:
            return matched
        next_line = state.line
        if (next_line >= min(last, state.lineMax) or "$$" not in state.tokens[index + 1].content
                or not state.line_view(next_line).text.startswith("%")):
            return True

        probe = copy(state)
        probe.tokens = []
        probe.env = state.env.copy()
        probe.tex_comment_rows = None
        rule(probe, first, last, False)
        *args, content = probe.last_read
        view = probe.mapped_lines(*args).strip()
        if view.text != content.strip():
            return True
        tokens = []
        parse_inline(view.text, probe.env, tokens)
        display_positions = [region.view.positions for region in inline_regions(view, tokens)
                             if region.kind == "display"]
        rows = set()
        for row in range(next_line, probe.line):
            comment = state.line_view(row)
            if comment.text.startswith("%") and any(comment.at() in pos for pos in display_positions):
                rows.add(row)
        if next_line not in rows:
            return True

        del state.tokens[index:]
        state.line = line
        state.tex_comment_rows = rows
        try:
            return rule(state, first, last, False)
        finally:
            del state.tex_comment_rows
    return wrapped


def map_block(rule, name):
    def wrapped(state, first, last, silent):
        if name == "myst_target" and state.line_view(first).at() in state.env.get("hidden_targets", ()):
            return False
        index = len(state.tokens)
        matched = rule(state, first, last, silent)
        if not matched or silent:
            return matched
        tokens = state.tokens[index:]
        if name == "table":
            for token in tokens:
                if token.type == "tr_open":
                    cells = iter(table_views(state.line_view(token.map[0])))
                elif token.type == "inline":
                    token.meta["view"] = next(cells, View("", ()))
            return True
        for token in tokens:
            if name in {"paragraph", "lheading", "fence", "colon_fence"} and token.type in {
                "inline", "fence", "colon_fence",
            }:
                *args, expected = state.last_read
                view = state.mapped_lines(*args)
                if token.type == "inline":
                    view = view.strip()
                else:
                    token.meta["opening"] = state.line_view(first)
                    if args[1] < token.map[1]:
                        token.meta["closing"] = state.line_view(args[1])
                if view.text == (expected.strip() if token.type == "inline" else expected):
                    token.meta["view"] = view
            elif name == "heading" and token.type == "inline":
                line = state.line_view(first)
                after = re.match(r"#{1,6}(?=[ \t]|$)", line.text)
                if after:
                    body = line[after.end():].strip()
                    tail = re.search(r"[ \t]+#+$", body.text)
                    token.meta["view"] = body[:tail.start()].strip() if tail else body
            elif name == "myst_target":
                token.meta["view"] = state.line_view(first)
            elif name == "math_block":
                map_display(state, token, first)
                # 區塊數學插件會越過獨立 HTML 註解行取到關閉美元。
                # 把衝突前綴留下，並讓 HTML 規則從註解本身重新解析。
                for row in range(first + 1, token.map[1]):
                    if state.line_view(row).text.startswith("<!--"):
                        state.line = token.map[1] = row
                        token.type = "ambiguous_math_block"
                        break
        return True
    return wrapped


def map_display(state, token, first):
    last = token.map[1] - 1
    opening, closing = state.line_view(first), state.line_view(last)
    match = DISPLAY_END.search(closing.text)
    token.meta["view"] = opening
    if (not match or escaped(closing.text, match.start()) or not opening.text.startswith("$$")
            or opening.text.startswith("$$$") or (first == last and match.start() <= 2)
            or (match[1] or "") != token.info
            or any(state.sCount[row] < state.blkIndent for row in range(first + 1, last + 1)
                   if not state.isEmpty(row))):
        return

    # 區塊插件直接擷取開閉標記間的原始字元，含外層引用前綴。
    begin = state.bMarks[first] + state.tShift[first] + 2
    end = state.bMarks[last] + state.tShift[last] + match.start()
    if state.src[begin:end] != token.content:
        return
    if first == last:
        body = opening[2:match.start()]
    else:
        start = state.env["source_view"][begin:state.eMarks[first] + 1]
        middle = state.mapped_lines(first + 1, last, state.blkIndent, True)
        body = join((start, middle, closing[:match.start()]))
    token.meta["body"] = body
    token.meta["formula_context"] = state.env["source_view"][begin - 2:end + 2]
    if match[1]:
        token.meta["equation_label"] = (match[1], closing.at(match.start(1)))


def display_inline(rule):
    """讓段落內雙美元公式依同一套 TeX 註解邊界尋找結尾。"""
    def wrapped(state, silent):
        original, start = state.src, state.pos
        if not original.startswith("$$", start):
            return rule(state, silent)

        rejected_stop = None
        try:
            while rule(state, True):
                stop = state.pos
                state.pos = start
                if stop > state.posMax:
                    break
                body = original[start + 2:stop - 2]
                if not ends_in_tex_comment(body):
                    if silent:
                        state.pos = stop
                    else:
                        rule(state, False)
                        state.tokens[-1].content = body
                    return True
                state.src = state.src[:stop - 2] + "__" + state.src[stop:]
                rejected_stop = stop
        finally:
            state.src = original

        if rejected_stop is None:
            return False
        # 保留未閉合片段，避免起始標記的第二個美元再被當作單美元開頭。
        line_end = original.find("\n", rejected_stop, state.posMax)
        state.pos = state.posMax if line_end < 0 else line_end
        if not silent:
            state.pending += original[start:state.pos]
        return True
    return wrapped


def mark_inline(rule, name):
    def wrapped(state, silent):
        start, limit, count = state.pos, state.posMax, len(state.tokens)
        if name in {"math_inline", "myst_role"}:
            if not rule(state, True):
                return False
            stop = state.pos
            state.pos = start
            if stop > limit:
                return False
            guards = state.env.get("inline_guards")
            if guards and state.src is guards[0]:
                conflict = next(((left, right) for left, right in guards[1]
                                 if left < stop and start < right), None)
                if conflict:
                    if silent:
                        return False
                    left, right = conflict
                    token = state.push("ambiguous_inline", "", 0)
                    token.meta["span"] = (start, stop)
                    # 讓原規則處理尚未讀取的 HTML 或連結。衝突範圍內不建立公式或引用。
                    state.pos = left if start < left else min(right, limit)
                    return True
        if not rule(state, silent):
            return False
        if not silent and len(state.tokens) > count:
            token = state.tokens[-1]
            if name == "link":
                link = next(t for t in state.tokens[count:] if t.type == "link_open")
                stop = state.md.helpers.parseLinkLabel(state, start, True) + 1
                link.meta["target_span"] = (stop, state.pos)
                if link.meta.get("label"):
                    if state.src[stop:state.pos] in ("", "[]"):
                        for child in state.tokens[count:]:
                            child.meta.pop("span", None)
            else:
                token.meta["span"] = (start, state.pos)
                token.meta["inline_limit"] = limit
        return True
    return wrapped


def open_comment(state, silent):
    """段落末端未閉合的行內 HTML 註解保持原樣。"""
    if not state.src.startswith("<!--", state.pos):
        return False
    if not silent:
        token = state.push("html_inline", "", 0)
        token.meta.update(span=(state.pos, state.posMax), unclosed_comment=True)
    state.pos = state.posMax
    return True


def markup_parser():
    md = MarkdownIt("commonmark", {"html": True, "store_labels": True}).use(myst_role_plugin)
    md.inline.ruler.after("html_inline", "open_comment", open_comment)
    for rule in list(md.inline.ruler.__rules__):
        if rule.name in {"myst_role", "backticks", "html_inline", "link", "image"}:
            md.inline.ruler.at(rule.name, mark_inline(rule.fn, rule.name))
    for rule in list(md.block.ruler.__rules__):
        if rule.name == "html_block":
            md.block.ruler.at(rule.name, comment_block(rule.fn), {"alt": rule.alt})
    return md


def parser(front, targets):
    md = (markup_parser().enable("table").use(colon_fence_plugin)
          .use(dollarmath_plugin, double_inline=True).use(myst_block_plugin)
          .use(footnote_plugin, move_to_end=False))
    guard = markup_parser()
    if front:
        md.use(front_matter_plugin)
    if not targets:
        md.disable("myst_target")

    def mapped_block(core):
        if core.src:
            block = MappedBlock(core.src, md, core.env, core.tokens)
            md.block.tokenize(block, block.line, block.lineMax)

    def parse_inline(text, env, tokens):
        checks = []
        if ("<" in text or "]" in text) and ("$" in text or "}" in text):
            preliminary = []
            guard.inline.parse(text, guard, env, preliminary)
            for candidate in preliminary:
                field = "span" if candidate.type in {"html_inline", "image"} else "target_span"
                span = candidate.meta.get(field)
                if span and span[0] < span[1]:
                    checks.append(span)
        env["inline_guards"] = (text, sorted(checks))
        md.inline.parse(text, md, env, tokens)
        env.pop("inline_guards", None)

    def guarded_inline(core):
        for token in core.tokens:
            if token.type == "inline":
                parse_inline(token.content, core.env, token.children)

    md.core.ruler.at("block", mapped_block)
    md.core.ruler.at("inline", guarded_inline)
    block_rules = {"paragraph", "heading", "lheading", "table", "myst_target",
                   "fence", "colon_fence", "math_block"}
    for rule in list(md.block.ruler.__rules__):
        if rule.name in block_rules:
            fn = rule.fn
            if rule.name in ("fence", "colon_fence"):
                fn = directive_fence(fn, rule.name)
            elif rule.name == "math_block":
                fn = display_block(fn)
            elif rule.name == "paragraph":
                fn = display_paragraph(fn, parse_inline)
            md.block.ruler.at(rule.name, map_block(fn, rule.name), {"alt": rule.alt})
        elif rule.name == "myst_line_comment":
            md.block.ruler.at(rule.name, paragraph_comment(rule.fn), {"alt": rule.alt})
    for rule in list(md.inline.ruler.__rules__):
        if rule.name == "math_inline":
            md.inline.ruler.at(rule.name, mark_inline(display_inline(rule.fn), rule.name))
    return md


def parse(view, front, hidden_targets=None):
    return parser(front, hidden_targets is not None).parse(
        view.text, {"source_view": view, "hidden_targets": hidden_targets or set()},
    )


def source_view(token):
    view = token.meta.get("view")
    return view if view is not None and view.text == token.content else None


def targets_in_code(view, front):
    # 錨點規則會中斷 CommonMark 段落。先以停用錨點的解析確認跨行 code span。
    if ")=" not in view.text or not ("`" in view.text or "<!--" in view.text):
        return set()
    hidden = set()
    for token in parse(view, front):
        inline = source_view(token) if token.type == "inline" else None
        if inline is None:
            continue
        for child in token.children:
            span = child.meta.get("span")
            if not span or child.type not in ("code_inline", "html_inline"):
                continue
            part = inline[slice(*span)]
            if "\n" not in part.text:
                continue
            if child.type == "code_inline" and not (
                part.text.startswith(child.markup) and part.text.endswith(child.markup)
                and (len(part.text) > 2 * len(child.markup))
            ):
                continue
            for line in part.lines()[1:]:
                line = line.strip()
                if ANCHOR.fullmatch(line.text):
                    hidden.add(line.at())
    return hidden


@dataclass
class Region:
    kind: str
    view: View
    value: str = ""
    context: str = ""
    at: int | None = None


def inline_regions(view, tokens):
    for token in tokens:
        span = token.meta.get("span")
        if span is None:
            continue
        start, stop = span
        part = view[start:stop]
        if token.type == "ambiguous_inline":
            yield Region("ambiguous_source", part, "行內標記跨過 HTML 或連結保護邊界")
        elif token.type in {"math_inline", "math_inline_double"}:
            fence = len(token.markup)
            body = part[fence:-fence]
            if (part.text[:fence] != token.markup or part.text[-fence:] != token.markup
                    or escaped(view.text, start) or escaped(part.text, len(part.text) - fence)
                    or body.text != token.content or body.text.startswith("$") or body.text.endswith("$")):
                yield Region("ambiguous_source", part, "美元標記與解析結果不一致")
            else:
                yield from dollar_regions(part, body, token.type == "math_inline_double")
                if token.type == "math_inline_double" and "`" not in body.text:
                    label = re.match(r"[ \t]*\(([^)\s]+)\)", view.text[stop:token.meta["inline_limit"]])
                    if label:
                        yield Region("def", view[stop + label.start(1):stop + label.end(1)], label[1])
        elif token.type == "myst_role":
            name = token.meta["name"]
            if name not in REF_ROLES and name != "math":
                continue
            marker = ROLE.match(part.text)
            if not marker:
                yield Region("ambiguous_source", part, "無法確認角色標記")
                continue
            ticks = marker[2]
            body = part[marker.end():-len(ticks)]
            if (marker[1] != name or not part.text.endswith(ticks) or part.text[-len(ticks) - 1] == "`"
                    or view.text[stop:stop + 1] == "`" or body.text.replace("\n", " ") != token.content
                    or "<!--" in body.text):
                yield Region("ambiguous_source", part, "角色邊界與解析結果不一致")
            elif name == "math":
                yield Region("math", body)
            elif match := REF_TARGET.fullmatch(token.content):
                yield Region("ref", part, match[1].strip(), part.text)


def dollar_regions(part, body, display):
    if "`" in body.text:
        yield Region("math_backticks", part)
    elif "<!--" in body.text or "-->" in body.text:
        yield Region("ambiguous_source", part, "公式包含 HTML 註解邊界")
    else:
        yield Region("display" if display else "math", body)


def options(lines):
    """傳回選項區末端及可核對的定義或改名位置。"""
    if not lines:
        return 0, []
    first = lines[0].strip()
    if first.text == "---":
        for end, line in enumerate(lines[1:], 1):
            if line.text.strip() == "---":
                break
        else:
            return len(lines), [Region("ambiguous_source", first, "YAML 選項沒有結尾")]
        block = join(lines[1:end])
        try:
            node = yaml.compose(block.text, Loader=yaml.SafeLoader)
            if node is None:
                return end + 1, []
            if not isinstance(node, yaml.MappingNode):
                raise ValueError
            keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
            if len(keys) != len(node.value) or len(keys) != len(set(keys)) or "<<" in keys:
                raise ValueError
            if "label" not in keys:
                return end + 1, []
            key, value = node.value[keys.index("label")]
            if (not isinstance(value, yaml.ScalarNode) or value.tag != "tag:yaml.org,2002:str"
                    or key.end_mark.index > value.start_mark.index or value.style in ("|", ">")
                    or value.start_mark.line != value.end_mark.line or not valid_label(value.value)):
                raise ValueError
            return end + 1, [Region("def", block[value.start_mark.index:value.end_mark.index], value.value)]
        except (ValueError, yaml.YAMLError):
            return end + 1, [Region("ambiguous_source", first, "YAML 選項或標籤無法唯一確認")]

    start = OPTION.fullmatch(lines[0].text.rstrip("\n"))
    if not start:
        return 0, []
    width = len(start[1].expandtabs(4))
    parsed = {}
    issue = False
    end = 0
    for line in lines:
        raw = line.text.rstrip("\n")
        if not raw.strip():
            break
        match = OPTION.fullmatch(raw)
        indent = len(raw[:len(raw) - len(raw.lstrip(" \t"))].expandtabs(4))
        if indent <= width and not match:
            break
        end += 1
        if not match or indent != width or match[2] in parsed:
            issue = True
        else:
            parsed[match[2]] = (line, match)
    reason = "選項有續行、縮排不一致或重複鍵"
    if issue:
        return end, [Region("ambiguous_source", first, reason)]
    issue = "label" in parsed and "name" in parsed
    result = [Region("ambiguous_source", first, "同時指定 label 與 name")] if issue else []
    key = "label" if "label" in parsed else "name"
    if key in parsed:
        line, match = parsed[key]
        value = match[3].split("%", 1)[0].strip()
        if valid_label(value):
            field = line[match.start(2):match.end(2)]
            result.append(Region("def" if key == "label" else "rename", field, value))
        else:
            result.append(Region("ambiguous_source", line, "標籤值無法確認"))
    return end, result


def valid_label(label):
    return bool(re.fullmatch(r"[^\s%<>{}`]+", label))


def regions(view, front=True):
    tokens = parse(view, front, targets_in_code(view, front))
    protected = []
    for token in tokens:
        if token.type != "inline" or not any(child.meta.get("unclosed_comment") for child in token.children):
            continue
        mapped = source_view(token)
        if mapped is None:
            continue
        for child in token.children:
            if not child.meta.get("unclosed_comment"):
                continue
            start = mapped.at(child.meta["span"][0])
            if start is None or any(left <= start < right for left, right in protected):
                continue
            index = view.positions.index(start)
            close = view.text.find("-->", index + 4)
            if close >= 0:
                tail = view.positions[close + 2]
                if tail is None:
                    continue
                protected.append((start, tail + 1))
            else:
                protected.append((start, max(pos for pos in view.positions if pos is not None) + 1))
            yield Region("ambiguous_source", mapped[slice(*child.meta["span"])],
                         "行內 HTML 註解跨過區塊邊界")
    for region in block_regions(view, tokens):
        first = region.at if region.at is not None else region.view.at()
        if not protected or first is None:
            yield region
            continue
        last = next((pos for pos in reversed(region.view.positions) if pos is not None), first)
        if not any(left <= max(first, last) and first < right for left, right in protected):
            yield region


def block_regions(view, tokens):
    for token in tokens:
        if token.type == "inline":
            mapped = source_view(token)
            if mapped is not None:
                yield from inline_regions(mapped, token.children)
            elif any(t.type.startswith("math_") or t.type == "ambiguous_inline"
                     or t.meta.get("name") in REF_ROLES | {"math"}
                     for t in token.children):
                row = view.lines()[token.map[0]]
                yield Region("ambiguous_source", row, "行內 token 無法對回來源")
        elif token.type == "myst_target":
            line = token.meta["view"]
            match = ANCHOR.fullmatch(line.text)
            if match and match[1] == token.content:
                yield Region("def", line, match[1])
            else:
                yield Region("ambiguous_source", line, "無法確認錨點邊界")
        elif token.type == "ambiguous_math_block":
            yield Region("ambiguous_source", token.meta["view"], "顯示公式跨過 HTML 註解邊界")
        elif token.type in {"math_block", "math_block_label"}:
            if "body" not in token.meta:
                yield Region("ambiguous_source", token.meta["view"], "無法核對顯示公式的開閉標記")
                continue
            yield from dollar_regions(token.meta["formula_context"], token.meta["body"], True)
            if "equation_label" in token.meta and not re.search(r"`|<!--|-->", token.meta["body"].text):
                label, at = token.meta["equation_label"]
                yield Region("def", token.meta["formula_context"], label, at=at)
        elif token.type in {"fence", "colon_fence"}:
            name = DIRECTIVE.match(token.info.strip())
            if token.markup[0] not in "`:":
                continue
            if not name:
                if token.info.lstrip().startswith("{"):
                    yield Region("ambiguous_source", token.meta["opening"], "無法確認指令標記")
                continue
            name = name[1]
            if name.split(":", 1)[0] in CODE:
                continue
            opening = token.meta["opening"]
            body = source_view(token)
            closing = token.meta.get("closing")
            if (name not in BODY or body is None or not opening.text.startswith(token.markup)
                    or DIRECTIVE.match(opening.text[len(token.markup):].strip()) is None
                    or closing is None or not re.fullmatch(re.escape(token.markup[0]) +
                                                           r"{%d,}[ \t]*" % len(token.markup), closing.text)):
                yield Region("ambiguous_source", opening, "指令類型或圍欄正文邊界無法確認")
                continue
            lines = body.lines()
            stop, found = options(lines)
            yield from found
            body = join(lines[stop:])
            if name == "math":
                # {math} 的正文是 LaTeX；其中的 HTML 註解仍受保護。
                cursor = 0
                for comment in math_comments(body.text):
                    if comment[0] == "%":
                        continue
                    yield Region("display", body[cursor:comment.start()])
                    cursor = comment.end()
                yield Region("display", body[cursor:])
            else:
                yield from regions(body, front=False)
