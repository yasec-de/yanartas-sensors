"""Emulate KiCad 10.99's line ending shapes (start_shape/end_shape) on schematic graphics.

KiCad 10.99 can put arrows, circles and squares on the ends of graphic lines and Bézier curves. KiCad 10 cannot, so
the converter draws them as separate filled shapes and trims the line body the same way KiCad 10.99 does.
The geometry follows common/line_ending.cpp and common/eda_shape.cpp of KiCad 10.99.
"""

import math
import uuid as uuidlib

from .sexpr import fmt_num

IU_PER_MM = 10000  # Schematic internal units are 100 nm
DEFAULT_RATIO = 5.0  # LINE_ENDING::DEFAULT_RATIO_LENGTH and DEFAULT_RATIO_WIDTH
UUID_NAMESPACE = uuidlib.UUID('8a4f0d9e-5a77-4c3e-9f0f-6c1f7d3b2a10')

# Gauss-Legendre nodes and weights KiCad uses for Bézier arc lengths
_GL_NODES = [0.0950125098376374, 0.2816035507792590, 0.4580167776572274, 0.6178762444026438,
             0.7554044083550030, 0.8656312023878318, 0.9445750230732326, 0.9894009349916499]
_GL_WEIGHTS = [0.1894506104550685, 0.1826034150449236, 0.1691565193950025, 0.1495959888165767,
               0.1246289712555339, 0.0951585116824928, 0.0622535239386479, 0.0271524594117541]


def kiround(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


class Ending:
    def __init__(self, node):
        self.style = str(node.first())
        length, width, stroke = node.child('length'), node.child('width'), node.child('stroke')
        self.length = kiround(float(length.first()) * IU_PER_MM) if length is not None else 0
        self.width = kiround(float(width.first()) * IU_PER_MM) if width is not None else 0
        sw = stroke.child('width') if stroke is not None else None
        self.stroke_width = kiround(float(sw.first()) * IU_PER_MM) if sw is not None else 0

    def size(self, line_width):
        auto = kiround(line_width * DEFAULT_RATIO)
        length = self.length or self.width or auto
        width = self.width or self.length or auto
        return length, width

    def shorten_depth(self, line_width):
        if self.style == 'none':
            return 0
        length, _ = self.size(line_width)
        raw = {'arrow': length, 'arrow_open': 0}.get(self.style, length // 2)
        if self.stroke_width > 0:
            raw = max(0, raw - self.stroke_width // 2)
        return raw

    def orientation_depth(self, line_width):
        if self.style == 'arrow_open':
            return self.size(line_width)[0]
        return self.shorten_depth(line_width)

    def outline(self, point, tangent, line_width):
        """ Points of the ending shape, rotated to the outward tangent (radians) and moved to ``point`` """
        sx, sy = self.size(line_width)
        hx, hy = sx // 2, sy // 2
        if self.style == 'arrow':
            local = [(0, 0), (-sx, hy), (-sx, -hy), (0, 0)]
        elif self.style == 'arrow_open':
            local = [(-sx, -hy), (0, 0), (-sx, hy)]
        elif self.style == 'circle':
            local = [(kiround(hx * math.cos(2*math.pi*i/32)), kiround(hy * math.sin(2*math.pi*i/32))) for i in range(33)]
        elif self.style == 'square':
            local = [(hx, hy), (hx, -hy), (-hx, -hy), (-hx, hy), (hx, hy)]
        else:
            return []
        c, s = math.cos(tangent), math.sin(tangent)
        return [(kiround(point[0] + x*c - y*s), kiround(point[1] + x*s + y*c)) for x, y in local]


# Bézier helpers, in float internal units

def _bez_point(b, t):
    u = 1 - t
    return tuple(u*u*u*b[0][i] + 3*u*u*t*b[1][i] + 3*u*t*t*b[2][i] + t*t*t*b[3][i] for i in range(2))


def _bez_speed(b, t):
    u = 1 - t
    d = [3*u*u*(b[1][i]-b[0][i]) + 6*u*t*(b[2][i]-b[1][i]) + 3*t*t*(b[3][i]-b[2][i]) for i in range(2)]
    return math.hypot(*d)


def _bez_length(b, t0=0.0, t1=1.0):
    if t1 <= t0:
        return 0.0
    half, mid = (t1 - t0) / 2, (t1 + t0) / 2
    return half * sum(w * (_bez_speed(b, mid - half*n) + _bez_speed(b, mid + half*n))
                      for n, w in zip(_GL_NODES, _GL_WEIGHTS))


def _bez_t_at_length(b, target, total):
    if target <= 0:
        return 0.0
    if target >= total:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _bez_length(b, 0, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _lerp(p, q, t):
    return (p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t)


def _bez_split(b, t):
    """ De Casteljau split, returns (left, right) """
    p01, p12, p23 = _lerp(b[0], b[1], t), _lerp(b[1], b[2], t), _lerp(b[2], b[3], t)
    p012, p123 = _lerp(p01, p12, t), _lerp(p12, p23, t)
    p = _lerp(p012, p123, t)
    return [b[0], p01, p012, p], [p, p123, p23, b[3]]


def _bez_sub(b, t0, t1):
    _, right = _bez_split(b, t0)
    left, _ = _bez_split(right, (t1 - t0) / (1 - t0) if t0 < 1 else 0)
    return left


def _angle(v):
    return math.atan2(v[1], v[0])


def bezier_endings(pts, start, end, lw):
    """ KiCad 10.99's trimmed curve (or None if nothing is left of it) and the tangents of its ends """
    b = [tuple(map(float, p)) for p in pts]
    sd = start.shorten_depth(lw) if start else 0
    ed = end.shorten_depth(lw) if end else 0
    total = None
    if sd <= 0 and ed <= 0:
        short = b
    else:
        total = _bez_length(b)
        if total <= 0 or sd + ed >= total:
            short = None
        else:
            t0, t1 = _bez_t_at_length(b, sd, total), _bez_t_at_length(b, total - ed, total)
            short = _bez_sub(b, t0, t1) if t1 > t0 else None

    def fallback(p, c, near):
        if p != c:
            return _angle((p[0]-c[0], p[1]-c[1]))
        q = _bez_point(b, near)
        return _angle((p[0]-q[0], p[1]-q[1]))

    tan_start = tan_end = None
    if short is not None:
        if math.hypot(b[0][0]-short[0][0], b[0][1]-short[0][1]) > 0:
            tan_start = _angle((b[0][0]-short[0][0], b[0][1]-short[0][1]))
        if math.hypot(b[3][0]-short[3][0], b[3][1]-short[3][1]) > 0:
            tan_end = _angle((b[3][0]-short[3][0], b[3][1]-short[3][1]))
    if tan_start is None:
        tan_start = fallback(b[0], b[1], 0.01)
    if tan_end is None:
        tan_end = fallback(b[3], b[2], 0.99)

    # Open arrows do not trim the curve, but are aligned to the curve over their length
    for which, ending in (('start', start), ('end', end)):
        if not ending or ending.style != 'arrow_open' or (depth := ending.orientation_depth(lw)) <= 0:
            continue
        total = _bez_length(b) if total is None else total
        if total <= 0:
            continue
        dist = min(depth, total)
        t = _bez_t_at_length(b, dist if which == 'start' else total - dist, total)
        sample = _bez_point(b, t)
        ep = b[0] if which == 'start' else b[3]
        if math.hypot(ep[0]-sample[0], ep[1]-sample[1]) > 0:
            if which == 'start':
                tan_start = _angle((ep[0]-sample[0], ep[1]-sample[1]))
            else:
                tan_end = _angle((ep[0]-sample[0], ep[1]-sample[1]))

    return short, tan_start, tan_end


def polyline_endings(pts, start, end, lw):
    """ Trimmed point list (or None) and end tangents of a graphic polyline """
    p = [tuple(map(float, q)) for q in pts]
    tan_start = _angle((p[0][0]-p[1][0], p[0][1]-p[1][1]))
    tan_end = _angle((p[-1][0]-p[-2][0], p[-1][1]-p[-2][1]))
    sd = start.shorten_depth(lw) if start else 0
    ed = end.shorten_depth(lw) if end else 0
    if sd <= 0 and ed <= 0:
        return p, tan_start, tan_end

    def move_towards(a, b, d):
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        return (a[0] + (b[0]-a[0])*d/length, a[1] + (b[1]-a[1])*d/length)

    out = list(p)
    if len(p) == 2:
        length = math.hypot(p[1][0]-p[0][0], p[1][1]-p[0][1])
        if sd + ed >= length:
            return None, tan_start, tan_end
    else:
        if sd >= math.hypot(p[1][0]-p[0][0], p[1][1]-p[0][1]) or ed >= math.hypot(p[-1][0]-p[-2][0], p[-1][1]-p[-2][1]):
            return None, tan_start, tan_end
    if sd > 0:
        out[0] = move_towards(p[0], p[1], sd)
    if ed > 0:
        out[-1] = move_towards(p[-1], p[-2], ed)
    return out, tan_start, tan_end


def mm(iu):
    return fmt_num(iu / IU_PER_MM, 4)


def format_sexp(expr, indent):
    """ Format a nested Python list like KiCad does: one list per line, (xy ...) points on one line """
    head, *rest = expr
    if not any(isinstance(r, list) for r in rest):
        return '(' + ' '.join([head] + [str(r) for r in rest]) + ')'
    inner = indent + '\t'
    lines = [f'({head}']
    if head == 'pts':
        lines.append(inner + ' '.join(format_sexp(r, inner) for r in rest))
    else:
        lines.extend(inner + format_sexp(r, inner) for r in rest)
    lines.append(indent + ')')
    return '\n'.join(lines)


def ending_shapes(ending, point, tangent, lw, color, with_uuid, uuid_seed):
    """ S-expressions (as nested lists) of KiCad 10 shapes that draw ``ending`` """
    pts = ending.outline(point, tangent, lw)
    if not pts:
        return []
    color_node = ['color', *color] if color else None
    fill = ['fill', ['type', 'color'], color_node] if color_node else ['fill', ['type', 'outline']]
    sx, sy = ending.size(lw)

    if ending.style == 'arrow_open':
        stroke_w = ending.stroke_width if ending.stroke_width > 0 else lw
        stroke = ['stroke', ['width', mm(stroke_w)], ['type', 'solid']] + ([color_node] if color_node else [])
        shape = ['polyline', ['pts', *(['xy', mm(x), mm(y)] for x, y in pts)], stroke, ['fill', ['type', 'none']]]
    else:
        # A negative width means no outline in KiCad 10, a plain filled ending in KiCad 10.99 has none either
        stroke_w = mm(ending.stroke_width) if ending.stroke_width > 0 else '-0.0001'
        stroke = ['stroke', ['width', stroke_w], ['type', 'solid']] + ([color_node] if color_node else [])
        if ending.style == 'circle' and sx == sy:
            shape = ['circle', ['center', mm(point[0]), mm(point[1])], ['radius', mm(sx // 2)], stroke, fill]
        else:
            shape = ['polyline', ['pts', *(['xy', mm(x), mm(y)] for x, y in pts)], stroke, fill]
    if with_uuid:
        shape.append(['uuid', f'"{uuidlib.uuid5(UUID_NAMESPACE, uuid_seed)}"'])
    return [shape]
