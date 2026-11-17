import csv, json, math, re, sys, collections
cpl, fitj, easydir = sys.argv[1:4]
FITS = json.load(open(fitj))
sys.argv = ['x', sys.argv[4], sys.argv[5], sys.argv[6], easydir, '/dev/null']
src = open(sys.argv[0] if False else __file__.replace('jlc_verify', 'jlc_fit')).read().split('out = {}')[0]
exec(src)  # reuse board-pad / EasyEDA parsing and PIN_MAP from jlc_fit.py
worst = []
for row in csv.DictReader(open(cpl)):
    ref = row['Designator']; r = FITS[ref]
    lc = FOOTPRINT_ONLY.get(r['value'], r['lcsc'])
    ep, _ = easy_pads(lc); bp = board[ref]
    if lc in PIN_MAP: bp = {PIN_MAP[lc][k]: v for k, v in bp.items()}
    X, Y = float(row['Mid X'][:-2]), float(row['Mid Y'][:-2]); a = math.radians(float(row['Rotation']))
    bottom = row['Layer'] == 'Bottom'; d = 0
    for n in set(ep) & set(bp):
        ex, ey = mean(ep[n])
        if bottom: ex = -ex
        px, py = X + ex * math.cos(a) - ey * math.sin(a), Y + ex * math.sin(a) + ey * math.cos(a)
        bx, by = mean(bp[n]); d = max(d, math.hypot(px - bx, py - by))
    worst.append((d, ref, row['Layer']))
worst.sort(reverse=True)
print('rows checked:', len(worst), ' worst pad offsets (mm):', [(round(d, 3), r, l) for d, r, l in worst[:6]])
print('any > 0.25 mm:', [w for w in worst if w[0] > 0.25])
