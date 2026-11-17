"""Conversion steps shared between boards, footprints, schematics and symbol libraries."""

import base64
import io
import math
import struct
import logging

from .sexpr import fmt_num

log = logging.getLogger(__name__)

KICAD10_GENERATOR_VERSION = '10.0'

# KiCad 10.99 (file versions 20260826 and up) stores the base stroke width of bold stroke-font text and draws it this
# much wider. KiCad 10 stores the width it draws. (include/gr_text.h, BOLD_STROKE_MULTIPLIER)
BOLD_STROKE_MULTIPLIER = 1.6
BOLD_BASE_WIDTH_VERSION = 20260826

# Up to version 20260623, KiCad computed the resolution of PNG images from a truncated pixels/cm value and stored
# image scales relative to that. (common/bitmap_base.cpp, BITMAP_BASE::GetLegacyPPI)
IMAGE_PPI_FIX_VERSION = 20260623


class ConversionError(Exception):
    pass


def kiround(x):
    """ KiCad's KiROUND: round half away from zero """
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


class Report:
    """ What the conversion of one file did, for the log and the summary """

    def __init__(self, path):
        self.path = path
        self.changes = {}
        self.warnings = []

    def count(self, what, n=1):
        self.changes[what] = self.changes.get(what, 0) + n

    def warn(self, msg):
        self.warnings.append(msg)
        log.warning('%s: %s', self.path, msg)


def file_version(root):
    if (v := root.child('version')) is None:
        raise ConversionError(f'{root.head} has no (version ...)')
    return int(v.first())


def set_header(ed, root, version, report, generator=None):
    """ Rewrite (version ...), (generator ...) and (generator_version ...) of a file or footprint """
    ed.replace_value(root.child('version').values[0], str(version))
    if generator is not None and (g := root.child('generator')) is not None:
        ed.replace_value(g.values[0], f'"{generator}"')
    if (gv := root.child('generator_version')) is not None:
        ed.replace_value(gv.values[0], f'"{KICAD10_GENERATOR_VERSION}"')
    report.count('file header')


def migrate_bold_width(ed, effects, decimals, report):
    """ Undo KiCad 10.99's base-width storage of bold stroke-font text in an (effects (font ...)) node """
    font = effects.child('font')
    if font is None or not font.flag('bold'):
        return
    # Outline fonts (face "...") never had the bold width baked in
    if font.child('face') is not None:
        return
    if (th := font.child('thickness')) is None or not th.values:
        return  # Automatic width
    value = th.values[0]
    if float(value.value) <= 0:
        return
    ed.replace_value(value, fmt_num(float(value.value) * BOLD_STROKE_MULTIPLIER, decimals))
    report.count('bold text stroke width')


# PNG helpers. Images are embedded base64-encoded in (image ... (data "..." "...")).

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def png_chunks(data):
    if not data.startswith(PNG_MAGIC):
        return None
    pos, chunks = len(PNG_MAGIC), []
    while pos + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos+8])
        chunks.append((kind, data[pos+8:pos+8+length], data[pos:pos+12+length]))
        pos += 12 + length
    return chunks


def png_ppi(data):
    """ (KiCad 10.99's PPI, KiCad 10's PPI) of a PNG image, or None if it has no physical resolution """
    chunks = png_chunks(data)
    if not chunks:
        return None
    for kind, body, _raw in chunks:
        if kind == b'pHYs' and len(body) >= 9:
            ppm_x, _ppm_y, unit = struct.unpack('>IIB', body[:9])
            if unit != 1:
                # wxWidgets passes the raw value through, which both versions read the same
                return None
            # wxWidgets stores pixels/cm as a decimal string, e.g. "37.8"
            px_per_cm = ppm_x / 100.0
            if px_per_cm <= 1:
                return None
            new_ppi = kiround(px_per_cm * 2.54)
            # GetLegacyPPI() falls back to the current PPI if the truncated value is too small
            legacy_ppi = kiround(int(px_per_cm) * 2.54) if int(px_per_cm) > 1 else new_ppi
            return new_ppi, legacy_ppi
    return None


def png_replace_phys(new_png, old_png):
    """ Make the pHYs chunk of ``new_png`` byte-identical to the one of ``old_png`` """
    new_chunks, old_chunks = png_chunks(new_png), png_chunks(old_png)
    old_phys = [raw for kind, _, raw in old_chunks if kind == b'pHYs']
    out = [PNG_MAGIC]
    for kind, _body, raw in new_chunks:
        if kind == b'pHYs':
            continue
        out.append(raw)
        if kind == b'IHDR':
            out.extend(old_phys)
    return b''.join(out)


def bake_image(data, rotation, opacity):
    """ Rotate (degrees, counter-clockwise like KiCad) and fade an image, keeping its resolution chunk """
    try:
        from PIL import Image
    except ImportError:
        raise ConversionError('Pillow is needed to convert rotated or translucent images')

    img = Image.open(io.BytesIO(data))
    img.load()
    if opacity < 1.0:
        img = img.convert('RGBA')
        alpha = img.getchannel('A').point(lambda a: round(a * opacity))
        img.putalpha(alpha)
    if rotation % 360:
        exact = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}
        if (r := round(rotation % 360, 6)) in exact:
            img = img.transpose(exact[r])
        else:
            img = img.convert('RGBA').rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)
    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    out = out.getvalue()
    if png_chunks(data):
        out = png_replace_phys(out, data)
    return out


def convert_image(ed, image, file_version, report):
    """ Convert a reference image: KiCad 10 can neither rotate images nor draw them translucent, so bake rotation and
    opacity into the pixels, and undo 10.99's scale migration for the corrected PNG resolution. """
    rotate, opacity, scale, data = (image.child(k) for k in ('rotate', 'opacity', 'scale', 'data'))
    rotation = float(rotate.first()) if rotate is not None else 0.0
    alpha = float(opacity.first()) if opacity is not None else 1.0
    raw = base64.b64decode(''.join(v.value for v in data.values)) if data is not None else b''

    if file_version >= IMAGE_PPI_FIX_VERSION and data is not None and (ppi := png_ppi(raw)):
        new_ppi, legacy_ppi = ppi
        if new_ppi != legacy_ppi:
            old = float(scale.first()) if scale is not None else 1.0
            fixed = f'{old * legacy_ppi / new_ppi:g}'
            if scale is not None:
                ed.replace_value(scale.values[0], fixed)
            else:
                ed.insert(image.child('layer').end if image.child('layer') else image.child('at').end, f' (scale {fixed})')
            report.count('image scale')

    if (rotation % 360 or alpha < 1.0) and data is not None:
        baked = base64.b64encode(bake_image(raw, rotation, alpha)).decode()
        lines = [baked[i:i+76] for i in range(0, len(baked), 76)]
        vals = data.values
        indent = ed.text[vals[0].end:vals[1].start] if len(vals) > 1 else ' '
        ed.replace(vals[0].start, vals[-1].end, indent.join(f'"{l}"' for l in lines))
        report.count('image rotation/opacity baked into pixels')

    for n in (rotate, opacity):
        if n is not None:
            ed.delete_node(n)
