import base64
import io
import json
import math
import struct
import zlib

import pytest

from kicad10_compat import convert_board, convert_schematic, convert_project, ConversionError
from kicad10_compat.sexpr import parse
from kicad10_compat.verify import check_sexpr_file
from kicad10_compat import common


BOARD = '''(kicad_pcb
\t(version 20261031)
\t(generator "pcbnew")
\t(generator_version "10.99")
\t(footprint "R"
\t\t(layer "F.Cu")
\t\t(uuid "0f9e1b9a-0000-4000-8000-000000000001")
\t\t(transform
\t\t\t(translate 10.5 -3)
\t\t\t(rotate 90)
\t\t\t(scale 1 1)
\t\t)
\t\t(height 1.2)
\t\t(property "Reference" "R1"
\t\t\t(at 0 -1 90)
\t\t\t(layer "F.SilkS")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.1)
\t\t\t\t\t(bold yes)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(constraint
\t\t\t(type coincident)
\t\t\t(uuid "0f9e1b9a-0000-4000-8000-000000000002")
\t\t\t(members
\t\t\t\t(member "0f9e1b9a-0000-4000-8000-000000000003" start)
\t\t\t\t(member "0f9e1b9a-0000-4000-8000-000000000004" end)
\t\t\t)
\t\t)
\t)
\t(footprint "C"
\t\t(layer "F.Cu")
\t\t(transform (translate 1 2) (rotate 0) (scale 1 1))
\t)
)
'''


def test_board():
    out, report = convert_board(BOARD)
    root = parse(out)
    assert root.child('version').first() == 20260206
    assert root.child('generator_version').first() == '10.0'
    r, c = root.children('footprint')
    assert [v.value for v in r.child('at').values] == [10.5, -3, 90]
    assert [v.value for v in c.child('at').values] == [1, 2]
    assert r.child('transform') is None and r.child('height') is None and r.child('constraint') is None
    # Bold stroke-font text is drawn 1.6 times as wide as 10.99 stores it
    assert '(thickness 0.16)' in out
    assert check_sexpr_file(out) == []
    # Nothing else changes
    assert out.count('\n') == BOARD.count('\n') - 13


def test_board_scaled_footprint():
    with pytest.raises(ConversionError):
        convert_board(BOARD.replace('(scale 1 1)', '(scale 2 2)', 1))


def test_board_already_compatible():
    text = BOARD.replace('20261031', '20260206')
    assert convert_board(text)[0] == text


def test_footprint_library():
    lib = '(kicad_footprint_lib\n\t(version 20261031)\n\t(generator "kicad_footprint_editor")\n' \
          '\t(generator_version "10.99")\n\t(footprint "X"\n\t\t(layer "F.Cu")\n\t\t(embedded_fonts no)\n\t)\n)\n'
    out, _ = convert_board(lib)
    assert out == '(footprint "X"\n\t(version 20260206)\n\t(generator "pcbnew")\n\t(generator_version "10.0")' \
                  '\n\t(layer "F.Cu")\n\t(embedded_fonts no)\n)\n'


def _png(w, h, ppm=None):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    rows = b''.join(b'\0' + bytes([255, 0, 0, 255]) * w for _ in range(h))
    data = common.PNG_MAGIC + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    if ppm:
        data += chunk(b'pHYs', struct.pack('>IIB', ppm, ppm, 1))
    return data + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def test_image_scale_and_baking():
    png = base64.b64encode(_png(4, 2, ppm=3780)).decode()
    board = BOARD.replace('\t(footprint "C"', f'\t(image (at 1 2) (layer "F.SilkS") (rotate 90) (scale 2) '
                                              f'(opacity 0.5) (data "{png}"))\n\t(footprint "C"')
    out, _ = convert_board(board)
    img = parse(out).child('image')
    assert img.child('rotate') is None and img.child('opacity') is None
    # 3780 px/m is 96.012 PPI, which KiCad 10 reads as int(37.8) * 2.54 = 94 PPI
    assert float(img.child('scale').first()) == pytest.approx(2 * 94 / 96, rel=1e-5)
    data = base64.b64decode(''.join(v.value for v in img.child('data').values))
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    assert im.size == (2, 4)
    assert im.convert('RGBA').getpixel((0, 0)) == (255, 0, 0, 128)
    assert common.png_ppi(data) == (96, 94)


SCHEMATIC = '''(kicad_sch
\t(version 20261106)
\t(generator "eeschema")
\t(generator_version "10.99")
\t(uuid "0f9e1b9a-0000-4000-8000-000000000010")
\t(paper "A4")
\t(lib_symbols)
\t(bezier
\t\t(pts
\t\t\t(xy 0 0) (xy 10 0) (xy 10 0) (xy 20 0)
\t\t)
\t\t(stroke
\t\t\t(width 0.2)
\t\t\t(type solid)
\t\t)
\t\t(start_shape circle)
\t\t(end_shape arrow)
\t\t(fill
\t\t\t(type none)
\t\t)
\t\t(uuid "0f9e1b9a-0000-4000-8000-000000000011")
\t)
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
'''


def test_schematic_line_endings():
    out, report = convert_schematic(SCHEMATIC)
    root = parse(out)
    assert root.child('version').first() == 20260306
    bez = root.child('bezier')
    assert bez.child('start_shape') is None and bez.child('end_shape') is None
    pts = [[v.value for v in xy.values] for xy in bez.child('pts').children('xy')]
    # Auto-sized endings are 5 line widths: the circle takes 0.5 mm off the start, the arrow 1 mm off the end
    assert pts[0] == [0.5, 0] and pts[3] == [19, 0]
    circle = root.child('circle')
    assert [v.value for v in circle.child('center').values] == [0, 0]
    assert circle.child('radius').first() == 0.5
    arrow = root.child('polyline')
    assert [[v.value for v in xy.values] for xy in arrow.child('pts').children('xy')] == \
        [[20, 0], [19, 0.5], [19, -0.5], [20, 0]]
    assert str(arrow.child('fill').child('type').first()) == 'outline'
    assert check_sexpr_file(out) == []


def test_symbol_library():
    lib = '(kicad_symbol_lib\n\t(version 20261015)\n\t(generator "kicad_symbol_editor")\n' \
          '\t(generator_version "10.99")\n)\n'
    out, _ = convert_schematic(lib)
    assert out == lib.replace('20261015', '20251024').replace('"10.99"', '"10.0"')


def test_too_new():
    with pytest.raises(ConversionError):
        convert_schematic(SCHEMATIC.replace('20261106', '20991231'))


def test_project():
    pro = {
        'meta': {'filename': 'x.kicad_pro', 'version': 4},
        'board': {'design_settings': {
            'meta': {'version': 4},
            'rule_severities': {'line_width': 'warning', 'text_thickness': 'error'},
            'rules': {'min_silk_line_width': 0.08},
            'drc_exclusions': [
                {'marker': {'error_type': 'DRCET_STARVED_THERMAL', 'layer': 'BL_In1_Cu', 'marker_type': 'MT_DRC',
                            'items': [{'value': 'a'}, {'value': 'b'}],
                            'position': {'x_nm': '1000', 'y_nm': '-2000'}},
                 'comment': 'fine'},
                {'marker': {'error_type': 'DRCET_LINE_WIDTH', 'items': [{'value': 'c'}], 'marker_type': 'MT_DRC',
                            'position': {'x_nm': '1', 'y_nm': '2'}}},
                {'marker': {'error_type': 'DRCET_VIA_STITCH_OVERLAP', 'items': [], 'position': {}}},
            ]}},
        'erc': {'meta': {'version': 1}, 'erc_exclusions': []},
        'tuning_profiles': {'meta': {'version': 2}, 'tuning_profiles_impedance_geometric': [
            {'profile_name': 'p', 'frequency': 1e9, 'model_solder_mask': True, 'net_chain_bridge_prop_delay': 0}]},
    }
    out, report = convert_project(json.dumps(pro))
    d = json.loads(out)
    bds = d['board']['design_settings']
    assert d['meta']['version'] == 3 and bds['meta']['version'] == 2
    assert bds['rule_severities'] == {'text_thickness': 'warning'}
    assert bds['rules'] == {'min_text_thickness': 0.08}
    assert bds['drc_exclusions'] == [
        ['starved_thermal|1000|-2000|a|b|In1.Cu', 'fine'],
        ['text_thickness|1|2|c|00000000-0000-0000-0000-000000000000', ''],
    ]
    assert len(report.warnings) == 1
    assert d['erc']['meta']['version'] == 0
    assert d['tuning_profiles'] == {'meta': {'version': 0},
                                    'tuning_profiles_impedance_geometric': [{'profile_name': 'p'}]}
