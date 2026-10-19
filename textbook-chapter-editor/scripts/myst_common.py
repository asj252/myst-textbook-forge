"""MyST blocks use line maps; an independent inline scanner preserves source.

No token content is searched for in the source. A text-token differential gates
each prose paragraph; uncertain paragraphs stay unchanged and become review notes.
"""
import html
import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from mdit_py_plugins.amsmath import amsmath_plugin
from mdit_py_plugins.colon_fence import colon_fence_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.myst_blocks import myst_block_plugin
from mdit_py_plugins.myst_role import myst_role_plugin
import yaml


class ParseError(ValueError):
    pass


CODE = {'code-cell', 'code', 'code-block', 'sourcecode', 'literalinclude',
        'mermaid', 'raw', 'csv-table', 'toctree', 'eval-rst', 'jupyter-execute', 'ipython'}
PATH = {'figure', 'image', 'include', 'bibliography', 'iframe', 'video', 'embed', 'glue:figure', 'glue'}
TEXT_OPTIONS = {'caption', 'title', 'alt', 'subtitle'}


def math_brackets(state, silent):
    start = state.pos
    pair = {'\\(': '\\)', '\\[': '\\]'}.get(state.src[start:start+2])
    if pair is None:
        return False
    end = state.src.find(pair, start+2, state.posMax)
    if end < 0:
        return False
    if not silent:
        token = state.push('math_inline', 'math', 0)
        token.content = state.src[start+2:end]
    state.pos = end+2
    return True


def parser(front=True):
    md = (MarkdownIt('commonmark', {'html': True, 'store_labels': True})
          .enable('table').use(colon_fence_plugin).use(dollarmath_plugin)
          .use(myst_block_plugin).use(myst_role_plugin).use(footnote_plugin)
          .use(amsmath_plugin))
    md.inline.ruler.before('escape', 'math_bracket', math_brackets)

    def nested(rule, footnote=False):
        def wrapped(state, silent):
            start, before = state.pos, len(state.tokens)
            ok = rule(state, silent)
            if ok and not silent and len(state.tokens) > before:
                token = state.tokens[-1]
                # Only line offsets, never columns or source character maps.
                token.meta['body_line'] = state.src[:start+2].count('\n')
                token.meta['breaks'] = state.src[start:state.pos].count('\n')
                if footnote:
                    token.children = state.env['footnotes']['list'][token.meta['id']]['tokens']
            return ok
        return wrapped

    for item in list(md.inline.ruler.__rules__):
        if item.name in ('image', 'footnote_inline', 'backticks', 'math_inline', 'math_inline_double', 'math_bracket', 'myst_role'):
            md.inline.ruler.at(item.name, nested(item.fn, item.name == 'footnote_inline'))
    if front:
        md.use(front_matter_plugin)
    return md


def token_text(tokens):
    """Text children only; code, math, roles, HTML and footnote IDs are excluded."""
    out = []
    for token in tokens:
        if token.type == 'text':
            out.append(token.content)
        elif token.type in ('softbreak', 'hardbreak'):
            out.append('\n')
        elif token.children:
            out.append(token_text(token.children))
    return ''.join(out)


def iter_text(tokens, line):
    """Walk nested image/footnote bodies with line-only locations."""
    current = line
    for token in tokens:
        if token.type == 'text':
            yield current, token.content
        if token.children:
            yield from iter_text(token.children, line + token.meta.get('body_line', 0))
        if token.type in ('softbreak', 'hardbreak'):
            current += 1
        else:
            current += token.meta.get('breaks', 0)


def canonical(text):
    # CommonMark escapes/entities and whitespace are the only normalization.
    text = re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', text)
    return re.sub(r'\s+', '', html.unescape(text))


def closing(src, start, left, right):
    depth, i = 1, start
    while i < len(src):
        if src[i] == '\\':
            i += 2
            continue
        if src[i] == '`':
            run = re.match(r'`+', src[i:])[0]
            end = re.search(r'(?<!`)'+re.escape(run)+r'(?!`)', src[i+len(run):])
            if end:
                i += len(run) + end.end()
                continue
        depth += (src[i] == left) - (src[i] == right)
        if depth == 0:
            return i
        i += 1
    return -1


def inline_kinds(src, env=None):
    """Small lexical scanner. It never consumes markdown-it token positions."""
    kinds = ['prose'] * len(src)

    def mark(a, b, kind='keep'):
        kinds[a:b] = [kind] * (b-a)

    i = 0
    while i < len(src):
        tail = src[i:]
        if src[i] == '\\' and not tail.startswith(('\\(', '\\[')):
            if i+1 < len(src):
                mark(i, i+1)
                i += 2
                continue
        if src[i] == '`':
            run = re.match(r'`+', tail)[0]
            end = re.search(r'(?<!`)'+re.escape(run)+r'(?!`)', src[i+len(run):])
            if end:
                stop = i+len(run)+end.end()
                mark(i, stop)
                i = stop
                continue
            return ['keep'] * len(src)  # Unpaired: retain the whole paragraph.
        role = re.match(r'\{[\w:.-]+\}(`+)', tail)
        if role:
            run = role[1]
            end = src.find(run, i+role.end())
            if end >= 0:
                stop = end+len(run)
                mark(i, stop)
                i = stop
                continue
        sub = re.match(r'\{\{[^}]*\}\}', tail)
        if sub:
            mark(i, i+sub.end())
            i += sub.end()
            continue
        pair = {'\\(': '\\)', '\\[': '\\]'}.get(tail[:2])
        if pair or src[i] == '$':
            left = tail[:2] if pair else ('$$' if tail.startswith('$$') else '$')
            right = pair or left
            end = re.search(r'(?<!\\)'+re.escape(right), src[i+len(left):])
            if end:
                stop = i+len(left)+end.end()
                mark(i, stop, 'math')
                i = stop
                continue
            return ['keep'] * len(src)
        tag = re.match(r'<!--.*?-->|</?[A-Za-z](?:[^<>"\']|"[^"]*"|\'[^\']*\')*>|<https?://[^>]+>', tail, re.S)
        if tag:
            mark(i, i+tag.end())
            i += tag.end()
            continue
        url = re.match(r'https?://[^\s<>「」，。；、]+', tail, re.I)
        if url:
            mark(i, i+url.end())
            i += url.end()
            continue
        if tail.startswith('^['):
            end = closing(src, i+2, '[', ']')
            if end >= 0:
                mark(i, i+2)
                kinds[i+2:end] = inline_kinds(src[i+2:end], env)
                mark(end, end+1)
                i = end+1
                continue
        if tail.startswith('[^'):
            end = src.find(']', i+2)
            if end >= 0:
                mark(i, end+1)
                i = end+1
                continue
        image = tail.startswith('![')
        if src[i] == '[' or image:
            a = i+2 if image else i+1
            end = closing(src, a, '[', ']')
            if end >= 0:
                stop = end+1
                full, valid = False, False
                if src[stop:stop+1] == '(':
                    dest = closing(src, stop+1, '(', ')')
                    if dest >= 0 and not re.search(r'(?<!\\)\s', src[stop+1:dest].strip().split(' "')[0]):
                        stop, full, valid = dest+1, True, True
                elif src[stop:stop+1] == '[':
                    dest = src.find(']', stop+1)
                    if dest >= 0:
                        label = src[stop+1:dest] or src[a:end]
                        if canonical(label).upper() in (env or {}).get('references', {}):
                            stop, full, valid = dest+1, bool(src[stop+1:dest]), True
                elif canonical(src[a:end]).upper() in (env or {}).get('references', {}):
                    valid = True
                if valid:
                    mark(i, stop)
                    if full:
                        kinds[a:end] = inline_kinds(src[a:end], env)
                    i = stop
                    continue
        # Delimiters are syntax only if the differential agrees with the parser.
        if src[i] in '*_':
            mark(i, i+1)
        i += 1
    return kinds


@dataclass
class Event:
    kind: str
    text: str
    line: int
    meta: dict = field(default_factory=dict)


class Document:
    def __init__(self, text, front=True):
        if '\r' in text or '\x00' in text:
            raise ParseError('請先將換行統一為 LF，並移除 NUL')
        self.text = text
        self.lines = text.split('\n')
        self.line_kinds = [['keep'] * len(row) for row in self.lines]
        self.events, self.notes = [], []
        self._walk(text, list(range(len(self.lines))), front, 0)
        self.kinds = []
        for n, kinds in enumerate(self.line_kinds):
            if n:
                self.kinds.append('keep')
            self.kinds.extend(kinds)

    def _note(self, row, reason):
        note = (row+1, row+1, reason, self.lines[row])
        if note not in self.notes:
            self.notes.append(note)

    def _prose(self, row, body, start=0, env=None, table=False, expected=None):
        self._paragraph([(row, body, start)], env, table, expected)

    def _paragraph(self, parts, env=None, table=False, expected=None):
        body = '\n'.join(value for _, value, _ in parts)
        kinds = inline_kinds(body, env)
        if table:
            # Scan each cell independently: backticks do not span table cells.
            cells = re.split(r'(?<!\\)\|', body)
            kinds = []
            for i, cell in enumerate(cells):
                if i:
                    kinds.append('keep')
                kinds.extend(inline_kinds(cell, env))
            for m in re.finditer(r'(?<!\\)\|', body):
                kinds[m.start()] = 'keep'
        actual = ''.join(c for c, kind in zip(body, kinds) if kind == 'prose')
        if expected is None or canonical(actual) != canonical(expected):
            for row, _, _ in parts:
                self._note(row, '需要人工確認的位置：段落行內差分不一致或定界未配對，原樣保留')
            return
        offset = 0
        for row, value, start in parts:
            self.line_kinds[row][start:start+len(value)] = kinds[offset:offset+len(value)]
            offset += len(value)+1

    def _walk(self, src, rows, front, depth):
        if depth > 40:
            for row in rows:
                self._note(row, '需要人工確認的位置：directive 巢狀超過 40 層，原樣保留')
            return
        md, env = parser(front), {}
        tokens = md.parse(src, env)
        local = src.splitlines()
        expected_rows = {}
        uncertain_rows = set()
        for token in tokens:
            if token.type != 'inline' or token.map is None:
                continue
            first, last = token.map
            texts = token_text(token.children or []).split('\n')
            if len(texts) != last-first:
                uncertain_rows.update(range(first, last))
            else:
                for n, value in enumerate(texts, first):
                    expected_rows[n] = expected_rows.get(n, '') + value
        heading, table = False, False
        checked_rows = set()
        for tok in tokens:
            if tok.type == 'heading_open':
                heading = True
            elif tok.type == 'heading_close':
                heading = False
            elif tok.type == 'table_open':
                table = True
            elif tok.type == 'table_close':
                table = False
            if tok.map is None:
                continue
            a, b = tok.map
            if a >= len(rows):
                continue
            row = rows[a]
            if tok.type == 'myst_target':
                self.events.append(Event('target', tok.content, row+1))
            elif tok.type == 'inline':
                self.events.append(Event('heading' if heading else 'inline', tok.content, row+1, {'tokens': tok.children or []}))
                # Blocks decide eligible rows; prefix peeling is lexical only.
                parts = []
                for n in range(a, min(b, len(rows), len(local))):
                    if table and n in checked_rows:
                        continue
                    checked_rows.add(n)
                    raw = self.lines[rows[n]]
                    prefix = re.match(r'^(?:[ \t]*(?:>[ \t]?|(?:[-+*]|\d+[.)])[ \t]+))*[ \t]*(?:#{1,6}[ \t]+|\[\^[^]]+\]:[ \t]*)?', raw)[0]
                    if table:
                        self._prose(rows[n], raw[len(prefix):], len(prefix), env, True,
                                    None if n in uncertain_rows else expected_rows.get(n))
                    else:
                        parts.append((rows[n], raw[len(prefix):], len(prefix)))
                if parts:
                    self._paragraph(parts, env, expected=token_text(tok.children or []))
            elif tok.type in ('math_block', 'math_block_label', 'amsmath'):
                # amsmath's map end is inclusive; other block ends are exclusive.
                stop = b+1 if tok.type == 'amsmath' else b
                for n in range(a, min(stop, len(rows))):
                    self.line_kinds[rows[n]] = ['math'] * len(self.lines[rows[n]])
                    raw = local[n]
                    closing_math = (re.search(r'\\end\{[^}]+\}(.*)$', raw)
                                    if tok.type == 'amsmath' else
                                    re.search(r'\$\$([^$]*)$', raw) if n == stop-1 else None)
                    if closing_math and closing_math[1].strip() and not re.fullmatch(r'\s*\([^()]+\)\s*', closing_math[1]):
                        self.line_kinds[rows[n]] = ['keep'] * len(self.lines[rows[n]])
                        self._note(rows[n], '需要人工確認的位置：數學結尾同列有文字，原樣保留')
                meta = tok.meta.copy()
                if tok.type == 'math_block_label':
                    meta['label'] = tok.info
                self.events.append(Event('math', tok.content, row+1, meta))
            elif tok.type in ('fence', 'colon_fence'):
                directive = re.match(r'^\{([\w:.-]+)\}\s*(.*)$', tok.info.strip())
                if not directive:
                    for n in range(a, min(b, len(rows))):
                        self._note(rows[n], '程式碼圍欄未轉換')
                    continue
                name, title = directive.groups()
                event = Event('directive', title, row+1, {'name': name, 'tokens': []})
                self.events.append(event)
                if name not in CODE | PATH | {'solution'}:
                    event.meta['tokens'] = parser(False).parseInline(title, env)[0].children or []
                    opening = re.match(r'^.*?\{[\w:.-]+\}[ \t]*', self.lines[row])
                    if opening:
                        self._prose(row, self.lines[row][opening.end():], opening.end(), env,
                                    expected=token_text(event.meta['tokens']))
                body = tok.content.splitlines(keepends=True)
                body_rows = rows[a+1:a+1+len(body)]
                offset = self._options(body, body_rows, event, env)
                if name in CODE:
                    for n in range(a, min(b, len(rows))):
                        self._note(rows[n], '程式碼圍欄未轉換')
                elif name == 'math':
                    for r in body_rows[offset:]:
                        self.line_kinds[r] = ['math'] * len(self.lines[r])
                else:
                    self._walk(''.join(body[offset:]), body_rows[offset:], False, depth+1)
            elif tok.type in ('front_matter', 'code_block', 'html_block'):
                for n in range(a, min(b, len(rows))):
                    self._note(rows[n], tok.type+' 未轉換')
        for ref in env.get('references', {}).values():
            for n in range(*ref.get('map', (0, 0))):
                if n < len(rows):
                    self._note(rows[n], '連結參考定義未轉換')

    def _options(self, body, rows, event, env):
        if body and body[0].strip() == '---':
            stop = next((i for i in range(1, len(body)) if body[i].strip() == '---'), None)
            if stop is None:
                return 0
            try:
                node = yaml.compose(''.join(body[1:stop]))
                if node is not None and not isinstance(node, yaml.MappingNode):
                    raise ValueError('YAML options must be a mapping')
            except (yaml.YAMLError, ValueError):
                for r in rows[:stop+1]:
                    self._note(r, '需要人工確認的位置：YAML 選項不合法，原樣保留')
                return stop+1
            for key, val in node.value if node else []:
                if key.value in ('label', 'name') and isinstance(val, yaml.ScalarNode):
                    event.meta['label'] = val.value
                if (key.value in TEXT_OPTIONS and isinstance(val, yaml.ScalarNode)
                        and event.meta['name'] not in CODE):
                    # The complete option block stays protected by default.
                    # YAML supplies decoded scalars (without comments), never
                    # source character coordinates. Parse each scalar once.
                    first = val.start_mark.line+1
                    end = val.end_mark.line+1+(val.end_mark.column > 0)
                    content_first = first+1 if val.style in ('|', '>') else first
                    tokens = parser(False).parseInline(val.value, env)[0].children or []
                    self.events.append(Event('inline', val.value, rows[content_first]+1, {'tokens': tokens}))
                    parts = []
                    for i in range(content_first, min(end, stop)):
                        raw = self.lines[rows[i]]
                        container = re.match(r'^(?:[ \t]*(?:>[ \t]?|(?:[-+*]|\d+[.)])[ \t]+))*[ \t]*', raw)[0]
                        raw_body = raw[len(container):]
                        prefix = re.match(r'^'+re.escape(key.value)+r':[ \t]*', raw_body) if i == first else None
                        start = len(container)+(prefix.end() if prefix else 0)
                        parts.append((rows[i], raw[start:], start))
                    # Flow mappings and shared physical lines cannot isolate
                    # prose by line maps. Preserve them, including path/name.
                    if node.flow_style or key.start_mark.line != val.start_mark.line:
                        for i in range(first, min(end, stop)):
                            self._note(rows[i], '需要人工確認的位置：選項行無法獨立核對，原樣保留')
                    elif parts:
                        self._paragraph(parts, env, expected=token_text(tokens))
            return stop+1
        first = next((i for i, raw in enumerate(body) if raw.strip()), None)
        if first is None or not body[first].lstrip().startswith(':'):
            return 0
        stop = next((i for i in range(first, len(body)) if not body[i].strip()), len(body))
        # Colon options include indented and multiline values. Without a blank
        # separator even apparent prose stays protected; never tokenize it.
        for i in range(first, stop):
            opt = re.match(r'^\s*:([\w-]+):[ \t]*(.*?)\s*$', body[i])
            if opt and opt[1] in ('label', 'name'):
                event.meta['label'] = opt[2]
            self._note(rows[i], '需要人工確認的位置：冒號式選項區原樣保留，不轉換或收集候選')
        return stop

    def rows(self):
        return [_pieces(raw, kinds) for raw, kinds in zip(self.lines, self.line_kinds)]


def _pieces(text, kinds):
    result = []
    for char, kind in zip(text, kinds):
        if result and result[-1][0] == kind:
            result[-1] = (kind, result[-1][1]+char)
        else:
            result.append((kind, char))
    return result


def parse(text, front_matter=True):
    doc = Document(text, front_matter)
    return doc.rows(), doc.notes


def scan_inline(text):
    return _pieces(text, inline_kinds(text))
