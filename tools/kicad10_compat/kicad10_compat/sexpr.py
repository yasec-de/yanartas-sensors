"""Lossless S-expression tree and text editor for KiCad files.

The tree is built with gerbonara's KiCad S-expression tokenizer (``gerbonara.cad.kicad.sexp.term_regex``), but unlike
gerbonara's ``parse_sexp`` it remembers where in the file each node and value came from. The converters do not
re-serialize the tree. They collect edits against the original text instead, so everything they do not touch stays
byte for byte as KiCad wrote it.
"""

import re

from gerbonara.cad.kicad.sexp import term_regex, Atom, SexpError


class Value:
    """ A value inside a list: a bare atom, a quoted string or a number """

    __slots__ = ('value', 'start', 'end', 'quoted')

    def __init__(self, value, start, end, quoted):
        self.value, self.start, self.end, self.quoted = value, start, end, quoted

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return f'Value({self.value!r})'


class Node:
    """ A parenthesized list. ``items`` holds :py:class:`Value` and :py:class:`Node` objects in file order """

    __slots__ = ('items', 'start', 'end', 'parent')

    def __init__(self, start, parent):
        self.items, self.start, self.end, self.parent = [], start, None, parent

    @property
    def head(self):
        if self.items and isinstance(self.items[0], Value) and isinstance(self.items[0].value, Atom):
            return str(self.items[0].value)
        return None

    @property
    def values(self):
        """ The values following the head of this list, without sub-lists """
        return [i for i in self.items[1:] if isinstance(i, Value)]

    def children(self, head=None):
        return [i for i in self.items if isinstance(i, Node) and (head is None or i.head == head)]

    def child(self, head):
        for i in self.items:
            if isinstance(i, Node) and i.head == head:
                return i
        return None

    def first(self, default=None):
        """ The first value after the head """
        v = self.values
        return v[0].value if v else default

    def flag(self, head):
        """ Read a KiCad boolean like ``(bold yes)``, ``(bold)`` or a bare ``bold`` atom """
        if (c := self.child(head)) is not None:
            v = c.first()
            return v is None or str(v) in ('yes', 'true')
        return any(str(v.value) == head for v in self.values if isinstance(v.value, Atom))

    def walk(self):
        yield self
        for c in self.children():
            yield from c.walk()

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def text(self, src):
        return src[self.start:self.end]

    def __repr__(self):
        return f'Node({self.head!r} @{self.start})'


def parse(text):
    """ Parse a KiCad S-expression file into a :py:class:`Node` tree with source positions """
    root = Node(0, None)
    stack = [root]
    for m in re.finditer(term_regex, text):
        quoted, lparen, rparen, flt, integer, bare = m.groups()
        # The tokenizer regex swallows leading whitespace
        end = m.end()
        start = end - len(m.group().lstrip())
        if lparen:
            n = Node(start, stack[-1])
            stack[-1].items.append(n)
            stack.append(n)
        elif rparen:
            if len(stack) == 1:
                raise SexpError(f'Unbalanced closing parenthesis at offset {start}')
            stack.pop().end = end
        elif bare is not None:
            stack[-1].items.append(Value(Atom(bare), start, end, False))
        elif quoted is not None:
            stack[-1].items.append(Value(quoted, start, end, True))
        elif flt:
            stack[-1].items.append(Value(float(flt), start, end, False))
        elif integer:
            stack[-1].items.append(Value(int(integer), start, end, False))
    if len(stack) != 1:
        raise SexpError('Unbalanced opening parenthesis')
    tops = root.children()
    if len(tops) != 1:
        raise SexpError(f'Expected exactly one top-level expression, found {len(tops)}')
    tops[0].parent = None
    return tops[0]


def fmt_num(value, decimals=6):
    """ Format a number like KiCad does: fixed point, no trailing zeros, no negative zero """
    s = f'{value:.{decimals}f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def quote(s):
    """ Quote a string for a KiCad file """
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


class Editor:
    """ Collects non-overlapping edits against a source text and applies them all at once """

    def __init__(self, text):
        self.text = text
        self.edits = []

    def replace(self, start, end, new):
        self.edits.append((start, end, new))

    def replace_node(self, node, new):
        self.replace(node.start, node.end, new)

    def replace_value(self, value, new):
        self.replace(value.start, value.end, new)

    def insert(self, pos, new):
        self.replace(pos, pos, new)

    def line_indent(self, pos):
        """ The indentation of the line ``pos`` is on """
        line_start = self.text.rfind('\n', 0, pos) + 1
        m = re.match(r'[ \t]*', self.text[line_start:])
        return m.group()

    def delete_node(self, node):
        """ Delete a node. If it is the only thing on its line(s), delete the line(s) too. """
        start, end = node.start, node.end
        before = self.text.rfind('\n', 0, start)
        after = self.text.find('\n', end)
        after = len(self.text) if after < 0 else after
        if not self.text[before+1:start].strip() and not self.text[end:after].strip():
            self.replace(before if before >= 0 else 0, after, '')
        else:
            # Also eat the whitespace that separated it from the previous item
            ws = len(self.text[:start]) - len(self.text[:start].rstrip(' \t'))
            self.replace(start - ws, end, '')

    def apply(self):
        edits = sorted(self.edits, key=lambda e: (e[0], e[1]))
        for (s1, e1, _), (s2, e2, _) in zip(edits, edits[1:]):
            if s2 < e1:
                raise ValueError(f'Overlapping edits at offsets {s1}-{e1} and {s2}-{e2}')
        out = []
        pos = 0
        for s, e, new in edits:
            out.append(self.text[pos:s])
            out.append(new)
            pos = e
        out.append(self.text[pos:])
        return ''.join(out)
