"""Build JLCPCB BOM + CPL (csv and xlsx) from KiCad exports and the EasyEDA footprint fit."""
import csv, json, re, sys, collections
from openpyxl import Workbook
from openpyxl.styles import Font
fit_json, bom_raw, pos_raw, outdir, base = sys.argv[1:6]
fit = json.load(open(fit_json))
def natkey(r): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', r)]
bom = [x for x in csv.DictReader(open(bom_raw)) if not (x['DNP'].strip() or x['ExclBOM'].strip() or x['ExclBoard'].strip())]
pos = {p['Ref']: p for p in csv.DictReader(open(pos_raw))}
fitted = {x['Reference'] for x in bom}

def write(rows, header, stem, widths):
    with open(f'{outdir}/{stem}.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    wb = Workbook(); ws = wb.active; ws.title = stem.rsplit('-', 1)[-1].upper()
    ws.append(header)
    for c in ws[1]: c.font = Font(bold=True)
    for r in rows: ws.append(r)
    for col, wd in zip('ABCDEFGH', widths): ws.column_dimensions[col].width = wd
    wb.save(f'{outdir}/{stem}.xlsx')

# ---- BOM ----
groups = collections.defaultdict(list)
for x in bom:
    lcsc = x['LCSC'].strip(); lcsc = lcsc if re.fullmatch(r'C\d+', lcsc) else ''
    groups[(x['Value'], x['Footprint'].split(':', 1)[-1], lcsc)].append(x['Reference'])
bom_rows = [[v, ','.join(sorted(r, key=natkey)), fp, l] for (v, fp, l), r in
            sorted(groups.items(), key=lambda kv: natkey(min(kv[1], key=natkey)))]
write(bom_rows, ['Comment', 'Designator', 'Footprint', 'LCSC Part #'], f'{base}-BOM', (24, 60, 50, 14))

# ---- CPL ----
def snap(a):
    s = round(a / 90.0) * 90 % 360
    assert min(abs(a - s), 360 - abs(a - s)) < 1.0, a
    return s
corr_by_type = collections.defaultdict(set); cpl_rows = []; report = collections.defaultdict(list)
for ref in sorted(fitted, key=natkey):
    p = pos[ref]; r = fit[ref]; th = float(p['Rot']) % 360; bottom = p['Side'] == 'bottom'
    if r['status'] == 'no-lcsc':
        x, y, c, note = float(p['PosX']), float(p['PosY']), 0, 'no LCSC part: consigned, KiCad position/rotation used'
    else:
        assert r['residual'] < 0.25, (ref, r['residual'])
        c = snap(r['rot'] - ((180 - th) if bottom else th))
        x, y = r['mid']; note = '' if re.fullmatch(r'C\d+', r['lcsc']) else 'consigned; placement fitted to JLC footprint of delisted C18184981'
    rot = ((180 - th) if bottom else th) + c
    rot = round(rot % 360, 3) % 360
    if r['status'] != 'no-lcsc':
        d = abs((rot - r['rot'] + 180) % 360 - 180); assert d < 0.5, (ref, rot, r['rot'])
    key = (r['lcsc'] if re.fullmatch(r'C\d+', r['lcsc']) else 'consigned', r['footprint'].split(':', 1)[-1], r.get('easy_package') or '-', p['Side'])
    corr_by_type[key].add(c)
    report[key].append((ref, round(x - float(p['PosX']), 3), round(y - float(p['PosY']), 3), round(r.get('residual') or 0, 3), note))
    cpl_rows.append([ref, f'{x:.4f}mm', f'{y:.4f}mm', 'Bottom' if bottom else 'Top', f'{rot:g}'])
bad = {k: v for k, v in corr_by_type.items() if len(v) != 1}
assert not bad, bad
write(cpl_rows, ['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'], f'{base}-CPL', (12, 14, 14, 8, 10))

with open(f'{outdir}/{base}-rotation-corrections.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['LCSC Part #', 'KiCad footprint', 'JLC/EasyEDA package', 'Side', 'Rotation correction (deg)',
                'Max centroid shift (mm)', 'Max pad fit residual (mm)', 'Designators', 'Note'])
    for k in sorted(report, key=lambda k: (k[1], k[0], k[3])):
        v = report[k]
        w.writerow([*k, next(iter(corr_by_type[k])), f"{max(max(abs(a[1]), abs(a[2])) for a in v):.3f}",
                    f"{max(a[3] for a in v):.3f}", ','.join(sorted((a[0] for a in v), key=natkey)), v[0][4]])
print(len(bom_rows), 'BOM lines;', len(cpl_rows), 'CPL rows;', sum(1 for k, v in corr_by_type.items() if v != {0}), 'part types corrected')
