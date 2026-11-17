"""Command line interface: python -m kicad10_compat [options] [path ...]"""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import EXTENSIONS, convert_board, convert_schematic, convert_project, ConversionError
from .schematic import DEFAULT_LINE_WIDTH_MILS
from . import verify

SKIP_DIRS = {'.git', '.history', 'lib-src'}


def find_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob('*')):
                if f.suffix in EXTENSIONS and f.is_file() and not SKIP_DIRS & set(f.relative_to(p).parts):
                    yield p, f
        else:
            yield p.parent, p


def default_line_width_mils(sch_path):
    """ The schematic default line width of the project a schematic belongs to """
    for pro in (sch_path.with_suffix('.kicad_pro'), *sch_path.parent.glob('*.kicad_pro')):
        if pro.is_file():
            try:
                return json.loads(pro.read_text())['schematic']['drawing']['default_line_thickness']
            except (KeyError, ValueError):
                pass
    return DEFAULT_LINE_WIDTH_MILS


def read(path):
    # Keep line endings as they are
    with open(path, encoding='utf-8', newline='') as f:
        return f.read()


def convert_file(path, force=False):
    text = read(path)
    if path.suffix == '.kicad_pro':
        return text, *convert_project(text, str(path), force=force)
    if path.suffix in ('.kicad_pcb', '.kicad_mod'):
        return text, *convert_board(text, str(path), force=force)
    width = default_line_width_mils(path) if path.suffix == '.kicad_sch' else DEFAULT_LINE_WIDTH_MILS
    return text, *convert_schematic(text, str(path), force=force, default_line_width_mils=width)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m kicad10_compat', description=__doc__.splitlines()[0] + '. '
        'Converts KiCad 10.99 project (.kicad_pro), board (.kicad_pcb), schematic (.kicad_sch), symbol library '
        '(.kicad_sym) and footprint (.kicad_mod) files to the file format of KiCad 10.0.')
    parser.add_argument('paths', nargs='*', default=['.'], help='Files, or directories to search for KiCad files')
    parser.add_argument('-o', '--output', type=Path,
                        help='Write converted files here, mirroring the directory structure, instead of in place')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Convert and check, but do not write anything')
    parser.add_argument('--check', action='store_true',
                        help='Only check that the files are readable by KiCad 10, do not convert them')
    parser.add_argument('--force', action='store_true', help='Convert files newer than this converter knows')
    parser.add_argument('-v', '--verbose', action='store_true', help='List every change')
    args = parser.parse_args(argv)
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO if args.verbose else logging.WARNING)

    failed = False
    for base, path in find_files(args.paths):
        rel = path.relative_to(base) if args.output else path
        try:
            if args.check:
                original = converted = read(path)
                report = None
            else:
                original, converted, report = convert_file(path, force=args.force)
        except (ConversionError, ValueError) as e:
            print(f'FAILED  {rel}: {e}')
            failed = True
            continue

        problems = []
        if path.suffix == '.kicad_pro':
            problems += verify.check_project(converted)
        else:
            problems += verify.check_sexpr_file(converted)
        if path.suffix == '.kicad_sch' and converted != original:
            try:
                lost, gained = verify.compare_schematics(original, converted)
            except Exception as e:
                problems.append(f'gerbonara can not load the converted schematic: {e}')
            else:
                if args.verbose:
                    for (p, v), n in sorted(lost.items()):
                        print(f'        removed {n}x {"/".join(p)} {" ".join(map(str, v))}')
                    for (p, v), n in sorted(gained.items()):
                        print(f'        added   {n}x {"/".join(p)} {" ".join(map(str, v))}')

        status = 'OK     ' if not problems else 'PROBLEM'
        if report is None:
            print(f'{status} {rel}')
        elif converted == original:
            print(f'{status} {rel}: unchanged')
        else:
            changes = ', '.join(f'{what}: {n}' for what, n in report.changes.items())
            print(f'{status} {rel}: {changes}')
        for w in (report.warnings if report else []):
            print(f'        warning: {w}')
        for p in problems:
            print(f'        {p}')
        failed |= bool(problems)

        if report is not None and not args.dry_run and (args.output or converted != original):
            out = args.output / rel if args.output else path
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, 'w', encoding='utf-8', newline='') as f:
                f.write(converted)

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
