"""Reading the data a Next.js app-router page carries in its HTML (the RSC "flight" text).

The page ships its data as `self.__next_f.push([1, "<chunk>"])` script tags.
Joined, the chunks are rows of `<hex id>:<payload>`: JSON rows (a component
tree with its props, a plain value), text rows `<id>:T<hex byte length>,<raw
text>` for long strings, and module rows (`<id>:I[...]`) that hold no data.
A row is named from another one as "$<id>" (a text) or "$L<id>" (a part of
the tree that streamed later). Pure functions, standard library only.
"""
import json
import re

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)')
_ROW_RE = re.compile(rb"([0-9a-f]+):")
_REF_RE = re.compile(r"^\$L?([0-9a-f]+)$")
# How deep resolved() follows rows that name other rows.
MAX_DEPTH = 40


class _Text(str):
    """A text row's content. Flight writes it raw: a leading "$" in it is neither a reference nor an escape."""


def text_of(html):
    """The page's flight text: every pushed chunk, decoded and joined. '' for a page without one."""
    parts = []
    for match in _PUSH_RE.finditer(html or ""):
        try:
            parts.append(json.loads(match.group(1)))
        except ValueError:
            continue
    return "".join(part for part in parts if isinstance(part, str))


def rows(html):
    """Page HTML -> {row id: its JSON value, or its text for a text row}. Module rows and rows that do not
    parse are left out; {} for a page without flight data."""
    data = text_of(html).encode("utf-8", "surrogatepass")
    out = {}
    pos, end = 0, len(data)
    while pos < end:
        match = _ROW_RE.match(data, pos)
        if not match:
            nxt = data.find(b"\n", pos)
            if nxt < 0:
                break
            pos = nxt + 1
            continue
        row_id = match.group(1).decode()
        pos = match.end()
        if data[pos:pos + 1] == b"T":                    # a text row is read by its length: it may hold newlines
            comma = data.find(b",", pos)
            try:
                length = int(data[pos + 1:comma], 16)
            except ValueError:
                length = -1
            if comma > 0 and length >= 0:
                out[row_id] = _Text(data[comma + 1:comma + 1 + length].decode("utf-8", "replace"))
                pos = comma + 1 + length
                continue
        nxt = data.find(b"\n", pos)
        if nxt < 0:
            nxt = end
        raw = data[pos:nxt].decode("utf-8", "replace")
        pos = nxt + 1
        if raw[:1] in ("[", "{", '"') or raw in ("null", "true", "false") or raw[:1].isdigit():
            try:
                out[row_id] = json.loads(raw)
            except ValueError:
                pass
    return out


def resolved(value, all_rows, _depth=0, _seen=()):
    """`value` with every reference followed: "$<id>" and "$L<id>" become the row they name (when the page
    has that row), "$undefined" becomes None, and "$$text" becomes "$text" (how flight writes a literal
    leading "$"). A reference to a module row, or one that would loop, is left as written. A text row is
    raw text and comes back as it is."""
    if isinstance(value, str):
        if isinstance(value, _Text):
            return str(value)
        if value == "$undefined":
            return None
        if value.startswith("$$"):
            return value[1:]
        match = _REF_RE.match(value)
        if match and match.group(1) in all_rows and match.group(1) not in _seen and _depth < MAX_DEPTH:
            return resolved(all_rows[match.group(1)], all_rows, _depth + 1, _seen + (match.group(1),))
        return value
    if _depth >= MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {key: resolved(item, all_rows, _depth + 1, _seen) for key, item in value.items()}
    if isinstance(value, list):
        return [resolved(item, all_rows, _depth + 1, _seen) for item in value]
    return value


def dicts(value):
    """Every dict inside a JSON value, parents before children, in document order."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def elements(value):
    """Every element of a tree, as (tag, key, props): flight writes one as ["$", tag, key, {props}]. `tag`
    is an HTML tag ("div") or a component reference ("$L3a"); parents come before their children."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            if len(item) == 4 and item[0] == "$" and isinstance(item[1], str) and isinstance(item[3], dict):
                yield item[1], item[2], item[3]
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))


def props_with(all_rows, *keys):
    """Every dict in the page's rows that has all of `keys` (a component's props, a data object), each
    with its references followed, in row order. [] when there is none."""
    found = []
    for row in all_rows.values():
        if not isinstance(row, (dict, list)):
            continue
        for node in dicts(row):
            if all(key in node for key in keys):
                found.append(resolved(node, all_rows))
    return found
