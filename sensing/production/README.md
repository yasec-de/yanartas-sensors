# Sensing board: JLCPCB production files

Upload from `jlcpcb/`:

| JLCPCB order step | File |
|---|---|
| Gerber | `yanartas-pillowbox-sensing-Gerber.zip` (4 layers, Protel extensions, soldermask subtracted from silk, Excellon mm/decimal, PTH and NPTH separate, drill maps) |
| BOM | `yanartas-pillowbox-sensing-BOM.xlsx` (or `.csv`): Comment, Designator, Footprint, LCSC Part # |
| CPL | `yanartas-pillowbox-sensing-CPL.xlsx` (or `.csv`): Designator, Mid X, Mid Y, Layer, Rotation |

`yanartas-pillowbox-sensing-rotation-corrections.csv` lists the rotation and centroid correction used for each part type, for review.

## How the CPL is corrected

JLC places parts using the footprint from its own (EasyEDA) library, so KiCad rotations and origins don't always match. No hand-maintained offset table is used here. Instead, each part is placed from JLC's actual footprint:

1. `kicad-cli pcb export ipcd356` gives the board position of every pad.
2. The EasyEDA footprint of each LCSC part is fetched from `easyeda.com/api/products/<LCSC>/components`.
3. `tools/jlc_fit.py` fits that footprint onto the board pads, matching pin numbers (rigid 2D fit, mirrored for bottom-side parts). The result gives the JLC rotation, and the footprint origin gives Mid X/Y.
4. `tools/jlc_build.py` snaps each correction to a multiple of 90°. It checks that every instance of a part type got the same correction, then writes the BOM and CPL. Bottom-side angles use JLC's mirrored convention, `180 − θ + correction`.
5. `tools/jlc_verify.py` re-places JLC's footprints from the final CPL and checks that every pad lands within 0.25 mm of its board pad. The worst case is 0.18 mm, on L1–L3, because their KiCad pads are longer than JLC's. With uncorrected KiCad rotations, the same check fails by up to 9.6 mm.

Special cases, hard-coded in `tools/jlc_fit.py`:

- **C2290 LED (D12–D14):** EasyEDA numbers the pins 1 = A, 2 = K; KiCad numbers them 1 = K, 2 = A. Pins are matched by function, otherwise the LEDs would be placed reversed.
- **PI3WVR41310 (U3, U9):** you supply these (no orderable LCSC part). They are placed using JLC's footprint for the delisted C18184981.

DNP parts and parts excluded from BOM or position files are left out. The NT1–NT4 net ties and the H1 mounting hole are left out of the CPL.

## Regenerating

Requires a KiCad 10.99 nightly `kicad-cli` (the board format is newer than 10.0) and Python with `openpyxl`.

```bash
kicad-cli pcb export ipcd356 -o board.d356 yanartas-pillowbox-sensing.kicad_pcb
kicad-cli pcb export pos --format csv --units mm --side both --exclude-dnp -o pos_raw.csv yanartas-pillowbox-sensing.kicad_pcb
kicad-cli sch export bom --fields 'Reference,Value,Footprint,LCSC,LCSC_Alt,LSCS,${DNP},${EXCLUDE_FROM_BOM},${EXCLUDE_FROM_BOARD}' \
  --labels 'Reference,Value,Footprint,LCSC,LCSC_Alt,LSCS,DNP,ExclBOM,ExclBoard' --group-by '' -o bom_raw.csv yanartas-pillowbox-sensing.kicad_sch
# fetch easyeda/<LCSC>.json for every LCSC number in bom_raw.csv (plus C18184981), then:
python3 tools/jlc_fit.py board.d356 bom_raw.csv pos_raw.csv easyeda fit.json
python3 tools/jlc_build.py fit.json bom_raw.csv pos_raw.csv jlcpcb yanartas-pillowbox-sensing
python3 tools/jlc_verify.py jlcpcb/yanartas-pillowbox-sensing-CPL.csv fit.json easyeda board.d356 bom_raw.csv pos_raw.csv
```

Footprint and rotation data come from the JLCEDA/EasyEDA official library (https://lceda.cn/, https://easyeda.com).
