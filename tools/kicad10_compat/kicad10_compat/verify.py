"""Checks of converted files.

* Every list in a converted board, footprint, schematic or symbol library must start with a keyword KiCad 10.0's
  parsers know. The only exception are the free-form properties of generated objects like tuning patterns.
* The file version must be one KiCad 10.0 reads.
* Converted schematics must load in gerbonara's schematic model, and must contain everything the original contains,
  except for what the conversion removes on purpose.
"""

from collections import Counter
from pathlib import Path

from gerbonara.cad.kicad.sexp import parse_sexp, Atom

from .sexpr import parse
from .board import BOARD_VERSION_10
from .schematic import SCH_VERSION_10, SYMLIB_VERSION_10
from . import project

KEYWORDS = frozenset(l.strip() for l in (Path(__file__).parent / 'kicad10_keywords.txt').read_text().splitlines()
                     if l.strip() and not l.startswith('#'))

MAX_VERSIONS = {'kicad_pcb': BOARD_VERSION_10, 'footprint': BOARD_VERSION_10, 'kicad_sch': SCH_VERSION_10,
                'kicad_symbol_lib': SYMLIB_VERSION_10}


def unknown_keywords(root):
    """ (path, keyword) of lists that KiCad 10 would not understand """
    out = []

    def visit(node, path):
        for c in node.children():
            head = c.head
            # Layer definitions of boards: (layers (0 "F.Cu" signal) ...)
            if head is None and node.head == 'layers' and c.items and isinstance(c.items[0].value, int):
                continue
            if head is None:
                out.append(('/'.join(path), '<list without keyword>'))
                continue
            # The properties of generated objects (tuning patterns etc.) are free-form
            if node.head == 'generated' and head not in ('uuid', 'type', 'name', 'layer', 'members', 'locked'):
                continue
            if head not in KEYWORDS:
                out.append(('/'.join(path), head))
            visit(c, path + [head])

    if root.head not in KEYWORDS and root.head not in ('kicad_symbol_lib',):
        out.append(('', root.head))
    visit(root, [root.head])
    return out


def check_sexpr_file(text):
    """ Problems that would keep KiCad 10 from reading this file """
    problems = []
    root = parse(text)
    if root.head not in MAX_VERSIONS:
        return [f'unexpected file type {root.head}']
    version = int(root.child('version').first())
    if version > MAX_VERSIONS[root.head]:
        problems.append(f'file version {version} is newer than KiCad 10 reads ({MAX_VERSIONS[root.head]})')
    counts = Counter(unknown_keywords(root))
    for (path, kw), n in sorted(counts.items()):
        problems.append(f'{n}x ({kw} ...) in {path or "file"}, which KiCad 10 does not know')
    return problems


def check_project(text):
    """ Problems with the schema versions of a project file """
    import json
    data = json.loads(text)
    problems = []
    for path, (supported, _newest) in ((('meta',), project.PROJECT_SCHEMA),
                                       (('board', 'design_settings', 'meta'), project.BOARD_SETTINGS_SCHEMA),
                                       (('erc', 'meta'), project.ERC_SCHEMA),
                                       (('tuning_profiles', 'meta'), project.TUNING_SCHEMA)):
        node = data
        for key in path:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and node.get('version', 0) > supported:
            problems.append(f'{"/".join(path[:-1]) or "project"} schema version {node["version"]} is newer than '
                            f'KiCad 10 reads ({supported})')
    return problems


def _nodes(sexp_node, path=()):
    """ (path, values) of every list, numbers rounded so that 1 and 1.0 compare equal """
    head = str(sexp_node[0]) if sexp_node and isinstance(sexp_node[0], Atom) else ''
    here = path + (head,)
    values = tuple(round(float(v), 4) if isinstance(v, (int, float)) else str(v)
                   for v in sexp_node[1:] if not isinstance(v, list))
    yield here, values
    for child in sexp_node[1:]:
        if isinstance(child, list):
            yield from _nodes(child, here)


def compare_schematics(original, converted):
    """ Load the converted schematic in gerbonara, and return what it lost and gained compared to the original as
    Counters of (path, values). """
    from gerbonara.cad.kicad.schematic import Schematic
    Schematic.load(converted)
    a, b = Counter(_nodes(parse_sexp(original))), Counter(_nodes(parse_sexp(converted)))
    return a - b, b - a
