"""Convert KiCad 10.99 schematics (.kicad_sch) and symbol libraries (.kicad_sym) to KiCad 10."""

from .sexpr import parse, Editor
from .common import (ConversionError, Report, file_version, set_header, migrate_bold_width, convert_image,
                     BOLD_BASE_WIDTH_VERSION)
from . import line_endings as le

SCH_VERSION_10 = 20260306       # KiCad 10.0.x SEXPR_SCHEMATIC_FILE_VERSION
SYMLIB_VERSION_10 = 20251024    # KiCad 10.0.x SEXPR_SYMBOL_LIB_FILE_VERSION
# Newest file versions whose changes this converter knows about (KiCad master as of 2026-11-13)
SCH_VERSION_KNOWN = 20261106
SYMLIB_VERSION_KNOWN = 20261106

DEFAULT_LINE_WIDTH_MILS = 6


def convert_schematic(text, path='<schematic>', force=False, default_line_width_mils=DEFAULT_LINE_WIDTH_MILS):
    """ Convert the text of a schematic or symbol library. Returns (new text, :py:class:`Report`). """
    report = Report(path)
    root = parse(text)
    if root.head == 'kicad_sch':
        target, known = SCH_VERSION_10, SCH_VERSION_KNOWN
    elif root.head == 'kicad_symbol_lib':
        target, known = SYMLIB_VERSION_10, SYMLIB_VERSION_KNOWN
    else:
        raise ConversionError(f'{path}: not a schematic or symbol library ({root.head})')

    version = file_version(root)
    if version <= target:
        report.count('already readable by KiCad 10')
        return text, report
    if version > known and not force:
        raise ConversionError(f'{path}: file version {version} is newer than the newest one this converter knows '
                              f'({known}). Use --force to convert it anyway.')

    ed = Editor(text)
    set_header(ed, root, target, report)
    ctx = dict(version=version, report=report, ed=ed,
               line_width=round(default_line_width_mils * 25.4e-3 * le.IU_PER_MM))
    _visit(root, ctx)
    return ed.apply(), report


SHAPES_WITH_ENDINGS = ('bezier', 'polyline', 'arc')


def _visit(node, ctx):
    for c in node.children():
        head = c.head
        if head == 'effects':
            if ctx['version'] >= BOLD_BASE_WIDTH_VERSION:
                migrate_bold_width(ctx['ed'], c, 4, ctx['report'])
            continue
        if head == 'image':
            convert_image(ctx['ed'], c, ctx['version'], ctx['report'])
            continue
        if head in SHAPES_WITH_ENDINGS and (c.child('start_shape') is not None or c.child('end_shape') is not None):
            _convert_endings(c, ctx)
            continue
        _visit(c, ctx)


def _stroke(shape, ctx):
    """ Effective line width in internal units, and stroke color (None if unspecified) """
    stroke = shape.child('stroke')
    lw = 0
    color = None
    if stroke is not None:
        if (w := stroke.child('width')) is not None:
            lw = le.kiround(float(w.first()) * le.IU_PER_MM)
        if (col := stroke.child('color')) is not None:
            vals = [v.value for v in col.values]
            if any(float(v) != 0 for v in vals):
                color = [col_v for col_v in (ctx['ed'].text[v.start:v.end] for v in col.values)]
    if lw == 0:
        lw = ctx['line_width']
    return max(lw, 0), color


def _points(pts_node):
    return [(le.kiround(float(xy.values[0].value) * le.IU_PER_MM), le.kiround(float(xy.values[1].value) * le.IU_PER_MM))
            for xy in pts_node.children('xy')]


def _convert_endings(shape, ctx):
    ed, report = ctx['ed'], ctx['report']
    start_node, end_node = shape.child('start_shape'), shape.child('end_shape')
    start = le.Ending(start_node) if start_node is not None else None
    end = le.Ending(end_node) if end_node is not None else None
    for n in (start_node, end_node):
        if n is not None:
            ed.delete_node(n)

    if all(e is None or e.style == 'none' for e in (start, end)):
        return

    if shape.head == 'arc':
        report.warn(f'line endings on an arc at offset {shape.start} were dropped, the converter can not draw them')
        return

    lw, color = _stroke(shape, ctx)
    pts_node = shape.child('pts')
    pts = _points(pts_node)
    if shape.head == 'bezier':
        if len(pts) != 4:
            report.warn(f'Bézier curve at offset {shape.start} has {len(pts)} points, its line endings were dropped')
            return
        body, tan_start, tan_end = le.bezier_endings(pts, start, end, lw)
    else:
        if len(pts) < 2:
            return
        # Filled or closed polylines are polygons, which have no ends
        fill = shape.child('fill')
        filled = fill is not None and fill.child('type') is not None and str(fill.child('type').first()) != 'none'
        if filled or pts[0] == pts[-1]:
            report.warn(f'line endings on a closed or filled polyline at offset {shape.start} were dropped')
            return
        body, tan_start, tan_end = le.polyline_endings(pts, start, end, lw)

    if body is None:
        report.warn(f'{shape.head} at offset {shape.start} is shorter than its line endings, its body was kept untrimmed')
    elif (body := [(le.kiround(x), le.kiround(y)) for x, y in body]) != pts:
        for xy, (x, y) in zip(pts_node.children('xy'), body):
            ed.replace(xy.values[0].start, xy.values[1].end, f'{le.mm(x)} {le.mm(y)}')
        report.count('line bodies trimmed for line endings')

    uuid_node = shape.child('uuid')
    seed = str(uuid_node.first()) if uuid_node is not None else f'{ctx["report"].path}:{shape.start}'
    indent = ed.line_indent(shape.start)
    new = []
    for which, ending, point, tangent in (('start', start, pts[0], tan_start), ('end', end, pts[-1], tan_end)):
        if ending is None or ending.style == 'none':
            continue
        new += le.ending_shapes(ending, point, tangent, lw, color, uuid_node is not None, f'{seed}:{which}_shape')
        report.count(f'{ending.style} line endings drawn as shapes')
    if new:
        ed.insert(shape.end, ''.join('\n' + indent + le.format_sexp(s, indent) for s in new))
