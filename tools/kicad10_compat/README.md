# kicad10_compat: KiCad 10.99 to KiCad 10 converter

This repository is edited with a KiCad 10.99 development build. KiCad 10.0 (and so KiKit, which runs on KiCad's
`pcbnew` Python module) refuses to open its files. This converter rewrites them in the file format of KiCad 10.0.x.
The `kicad-10-compat` branch holds the converted files.

It converts:

| Files | From | To |
|---|---|---|
| Boards `.kicad_pcb` | 20261031 | 20260206 |
| Footprints `.kicad_mod` | 20261031 (`kicad_footprint_lib`) | 20260206 |
| Schematics `.kicad_sch` | 20261106 | 20260306 |
| Symbol libraries `.kicad_sym` | 20261106 | 20251024 |
| Projects `.kicad_pro` | schema 4 | schema 3 |

Files that KiCad 10 can already read are left alone, as are the files KiCad 10.99 did not change (`.kicad_prl`,
`.kicad_dru`, `fp-lib-table`, `sym-lib-table`).

## Setup and use

```sh
tools/kicad10_compat/setup-venv.sh
cd tools/kicad10_compat
.venv/bin/python -m kicad10_compat ../..            # convert the whole repository in place
.venv/bin/python -m kicad10_compat -o /tmp/k10 ../..  # or write the converted files elsewhere
.venv/bin/python -m kicad10_compat --check ../..    # only check that the files are readable by KiCad 10
.venv/bin/python -m pytest tests
```

`setup-venv.sh` builds gerbonara from jaseg's pull request series on GitHub (jaseg/gerbonara PR 15, which contains
PRs 11 to 14, plus PR 16; PR 10 is already in gerbonara's main branch). The converter reads files with gerbonara's
KiCad S-expression tokenizer. It does not re-serialize them, but edits the original text, so everything it does not
need to change stays byte for byte as KiCad wrote it. Converted schematics are loaded with gerbonara's schematic model
(which reads KiCad 9, 10 and 10.99 files with these PRs) and compared to the original as a check.

Every converted file is also checked against the keyword lists of KiCad 10.0.8's file parsers.

## What changes

Boards and footprints:

* `(transform (translate x y) (rotate a) (scale 1 1))` of footprints becomes `(at x y a)`. Pads and texts of footprints
  are stored in the same frame in both versions as long as the scale is 1. Scaled footprints, which KiCad 10 can not
  represent, stop the conversion.
* Library footprints lose the `(kicad_footprint_lib ...)` wrapper of 10.99.
* Geometric constraints (`(constraint ...)`) are removed. The constrained shapes are stored with their solved
  coordinates, so nothing moves; KiCad 10 just will not keep them together when you edit them.
* Footprint heights (`(height ...)`), the frequency-dependent dielectric model settings of the stackup and the PNG
  plot settings are removed. KiCad 10 has none of them.
* Reference images: KiCad 10 can not rotate images or draw them translucent, so rotation and opacity are baked into
  the image pixels. The image scale is converted back from 10.99's corrected PNG resolution calculation.
* Bold text in KiCad's stroke font: 10.99 stores the base stroke width and draws it 1.6 times as wide, 10.0 stores the
  width it draws. (All bold text in this repository uses the Inter outline font, which this does not affect.)

Schematics and symbol libraries:

* Line endings (`(start_shape ...)`, `(end_shape ...)`) of Bézier curves and graphic lines are drawn as separate filled
  circles and polygons, and the curves are trimmed like 10.99 does, so they look the same. Endings on arcs are dropped
  with a warning.
* Bold stroke-font text and images, like above.

Projects:

* DRC exclusions go back from 10.99's JSON objects to KiCad 10's marker strings. The `line_width` DRC check of 10.99
  is KiCad 10's `text_thickness`. ERC exclusions in the new format would be dropped with a warning (there are none).
* Tuning profile settings 10.99 added are removed, and the schema versions of all sections are set to KiCad 10's.

The converter knows the file format changes of KiCad master up to 2026-11-13 (board version 20261031, schematic
version 20261106). It refuses newer files unless run with `--force`, since they may contain changes it does not know.
