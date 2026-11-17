"""Convert KiCad 10.99 boards (.kicad_pcb) and footprints (.kicad_mod) to KiCad 10."""

import re

from .sexpr import parse, Editor
from .common import (ConversionError, Report, file_version, set_header, migrate_bold_width, convert_image,
                     BOLD_BASE_WIDTH_VERSION)

BOARD_VERSION_10 = 20260206     # KiCad 10.0.x SEXPR_BOARD_FILE_VERSION, also used for footprint files
# Newest file version whose changes this converter knows about (KiCad master as of 2026-11-13)
BOARD_VERSION_KNOWN = 20261031


def convert_board(text, path='<board>', force=False):
    """ Convert the text of a board or footprint file. Returns (new text, :py:class:`Report`). """
    report = Report(path)
    root = parse(text)
    if root.head not in ('kicad_pcb', 'footprint', 'kicad_footprint_lib'):
        raise ConversionError(f'{path}: not a board or footprint ({root.head})')

    version = file_version(root)
    if version <= BOARD_VERSION_10:
        report.count('already readable by KiCad 10')
        return text, report
    if version > BOARD_VERSION_KNOWN and not force:
        raise ConversionError(f'{path}: file version {version} is newer than the newest one this converter knows '
                              f'({BOARD_VERSION_KNOWN}). Use --force to convert it anyway.')

    ed = Editor(text)
    ctx = dict(version=version, report=report, ed=ed)

    if root.head == 'kicad_footprint_lib':
        return _convert_footprint_lib(root, ctx), report

    set_header(ed, root, BOARD_VERSION_10, report, generator='pcbnew' if root.head == 'footprint' else None)
    _visit(root, ctx)
    return ed.apply(), report


def _convert_footprint_lib(root, ctx):
    """ KiCad 10.99 wraps library footprints in (kicad_footprint_lib (version ...) ... (footprint ...)). KiCad 10
    expects a bare (footprint "name" (version ...) (generator ...) ...). """
    ed, report = ctx['ed'], ctx['report']
    fps = root.children('footprint')
    others = [c.head for c in root.children() if c.head not in ('version', 'generator', 'generator_version', 'footprint')]
    if len(fps) != 1 or others:
        raise ConversionError(f'{report.path}: unexpected footprint library contents')
    fp = fps[0]

    # Drop the wrapper, and move the header into the footprint
    ed.replace(root.start, fp.start, '')
    ed.insert(fp.items[1].end, f'\n\t\t(version {BOARD_VERSION_10})\n\t\t(generator "pcbnew")'
                               f'\n\t\t(generator_version "10.0")')
    ed.replace(fp.end, root.end, '')
    report.count('footprint library wrapper removed')
    _visit(fp, ctx)
    out = ed.apply()
    # The footprint was indented by one level inside the wrapper
    return re.sub(r'^\t', '', out, flags=re.M)


def _visit(node, ctx):
    ed, report = ctx['ed'], ctx['report']
    for c in node.children():
        head = c.head
        parent = node.head

        # Geometric constraints between board graphics (10.99 file version 20260624). KiCad 10 has no constraint
        # solver; the constrained shapes are stored with their solved coordinates, so the constraints can go.
        if head == 'constraint' and parent in ('kicad_pcb', 'footprint'):
            ed.delete_node(c)
            report.count('geometric constraints removed')
            continue

        # Footprint affine transform (20260616): (transform (translate x y) (rotate a) (scale sx sy)) replaced
        # (at x y a). Children of footprints are stored the same way as before as long as there is no scale.
        if head == 'transform' and parent == 'footprint':
            _convert_transform(c, ctx)
            continue

        # Footprint overall height (20261017)
        if head == 'height' and parent == 'footprint':
            ed.delete_node(c)
            report.count('footprint heights removed')
            continue

        # Frequency-dependent dielectric models (20260511). KiCad 10 skips these, remove them for a clean file.
        if head in ('spec_frequency', 'dielectric_model') and parent == 'layer':
            ed.delete_node(c)
            report.count('stackup dielectric model settings removed')
            continue

        # PNG plot settings, which KiCad 10 skips
        if head in ('pngdpi', 'pngantialias') and parent == 'pcbplotparams':
            ed.delete_node(c)
            report.count('PNG plot settings removed')
            continue

        if head == 'image':
            convert_image(ed, c, ctx['version'], report)
            continue

        if head == 'effects':
            if ctx['version'] >= BOLD_BASE_WIDTH_VERSION:
                migrate_bold_width(ed, c, 6, report)
            continue

        _visit(c, ctx)


def _convert_transform(tr, ctx):
    ed, report = ctx['ed'], ctx['report']
    unknown = [c.head for c in tr.children() if c.head not in ('translate', 'rotate', 'scale')]
    if unknown:
        raise ConversionError(f'{report.path}: footprint transform at offset {tr.start} has unknown parts {unknown}')
    translate, rotate, scale = tr.child('translate'), tr.child('rotate'), tr.child('scale')
    if scale is not None and any(float(v.value) != 1.0 for v in scale.values):
        raise ConversionError(f'{report.path}: footprint at offset {tr.parent.start} is scaled, which KiCad 10 can '
                              f'not represent')
    x, y = (ed.text[v.start:v.end] for v in translate.values) if translate is not None else ('0', '0')
    at = f'(at {x} {y}'
    if rotate is not None and float(rotate.first()) != 0:
        at += ' ' + ed.text[rotate.values[0].start:rotate.values[0].end]
    ed.replace_node(tr, at + ')')
    report.count('footprint transforms converted to (at ...)')
