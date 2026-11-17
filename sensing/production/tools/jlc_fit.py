"""Fit JLC/EasyEDA footprints onto KiCad board pad positions to derive JLC CPL rotation/centroid."""
import csv, json, math, re, sys, collections
d356, bom_raw, pos_raw, easydir, out_json = sys.argv[1:6]
MIL10 = 0.254  # EasyEDA unit in mm

# --- board pads (IPC-D-356, 0.0001 in, Y up) ---
txt = open(d356, encoding='latin-1').read().splitlines()
assert any(l.startswith('P  UNITS CUST 0') for l in txt), 'unexpected IPC-356 units'
board = collections.defaultdict(lambda: collections.defaultdict(list))
access = collections.defaultdict(set)
for l in txt:
    if not re.match(r'^3[1-6]7', l): continue
    ref, pin = l[20:26].strip(), l[27:31].strip()
    m = re.search(r'A(\d\d)X([+-]\d+)Y([+-]\d+)', l)
    if not m or not ref or ref == 'VIA': continue
    board[ref][pin].append((int(m.group(2)) * 0.00254, int(m.group(3)) * 0.00254))
    access[ref].add(m.group(1))

# --- fitted parts ---
bom = [x for x in csv.DictReader(open(bom_raw))
       if not (x['DNP'].strip() or x['ExclBOM'].strip() or x['ExclBoard'].strip())]
pos = {p['Ref']: p for p in csv.DictReader(open(pos_raw))}

def easy_pads(lcsc):
    d = json.load(open(f'{easydir}/{lcsc}.json'))['result']['packageDetail']['dataStr']
    ox, oy = float(d['head']['x']), float(d['head']['y'])
    pads = collections.defaultdict(list)
    for s in d['shape']:
        f = s.split('~')
        if f[0] != 'PAD' or f[6] not in ('1', '11'): continue
        pads[f[8]].append(((float(f[2]) - ox) * MIL10, -(float(f[3]) - oy) * MIL10))
    return pads, d['head']['c_para'].get('package')

def mean(pts): return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

def fit(src, dst):
    cs, cd = mean(src), mean(dst)
    sxx = sxy = 0.0
    for (ax, ay), (bx, by) in zip(src, dst):
        ax, ay, bx, by = ax - cs[0], ay - cs[1], bx - cd[0], by - cd[1]
        sxx += ax * bx + ay * by; sxy += ax * by - ay * bx
    phi = math.atan2(sxy, sxx); c, s = math.cos(phi), math.sin(phi)
    tx = cd[0] - (c * cs[0] - s * cs[1]); ty = cd[1] - (s * cs[0] + c * cs[1])
    res = max(math.hypot(c * ax - s * ay + tx - bx, s * ax + c * ay + ty - by) for (ax, ay), (bx, by) in zip(src, dst))
    return math.degrees(phi) % 360, (tx, ty), res

# Parts whose EasyEDA pin numbering differs from KiCad's in meaning (verified against EasyEDA symbol pin names).
# C2290 LED: KiCad Device:LED 1=K 2=A; EasyEDA symbol 1=A 2=K.
# Consigned parts without an orderable LCSC number: use the JLC library footprint of the delisted LCSC part for placement.
FOOTPRINT_ONLY = {'PI3WVR41310': 'C18184981'}
PIN_MAP = {'C2290': {'1': '2', '2': '1'}}
out = {}
for x in bom:
    ref, lcsc = x['Reference'], x['LCSC'].strip()
    p = pos[ref]; side = p['Side']
    rec = dict(ref=ref, lcsc=lcsc, footprint=x['Footprint'], value=x['Value'], side=side,
               kicad=(float(p['PosX']), float(p['PosY']), float(p['Rot']) % 360))
    if not re.fullmatch(r'C\d+', lcsc) and x['Value'] not in FOOTPRINT_ONLY:
        rec['status'] = 'no-lcsc'; out[ref] = rec; continue
    ep, pkg = easy_pads(FOOTPRINT_ONLY.get(x['Value'], lcsc)); bp = board[ref]
    rec['easy_package'] = pkg
    if lcsc in PIN_MAP:  # translate KiCad pin numbers to EasyEDA pin numbers by pin function
        bp = {PIN_MAP[lcsc][k]: v for k, v in bp.items()}
    common = sorted(set(ep) & set(bp), key=lambda s: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)])
    rec['pins_kicad'], rec['pins_easy'], rec['pins_common'] = sorted(bp), sorted(ep), common
    if len(common) < 2:
        rec['status'] = 'too-few-common-pins'; out[ref] = rec; continue
    src = [mean(ep[n]) for n in common]; dst = [mean(bp[n]) for n in common]
    if side == 'bottom':  # seen from top, bottom parts are mirrored; mirror about the part's Y axis
        src = [(-a, b) for a, b in src]
    phi, (tx, ty), res = fit(src, dst)
    eb = [q for v in ep.values() for q in v]
    rec.update(status='ok' if res < 0.05 else 'mismatch', rot=phi, mid=(tx, ty), residual=res,
               easy_origin_vs_padcenter=math.hypot(*[(min(q[i] for q in eb) + max(q[i] for q in eb)) / 2 for i in (0, 1)]))
    out[ref] = rec
json.dump(out, open(out_json, 'w'), indent=1)
by = collections.Counter(r['status'] for r in out.values()); print(dict(by))
for r in out.values():
    if r['status'] != 'ok':
        print(r['ref'], r['status'], r.get('easy_package'), 'kicad', r.get('pins_kicad'), 'easy', r.get('pins_easy'), 'res', r.get('residual'))
