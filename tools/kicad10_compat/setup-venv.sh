#!/bin/sh
# Create a Python virtualenv for the converter, with gerbonara built from jaseg's PR series
# (https://github.com/jaseg/gerbonara pull requests 10 to 16):
#
#   PR 10 is merged into gerbonara's main branch. PR 15 is stacked on top of PRs 11 to 14, so its head contains all of
#   them. PR 16 is independent of them and gets merged on top.
#
# Usage: tools/kicad10_compat/setup-venv.sh [venv directory, default: tools/kicad10_compat/.venv]
set -eu

here=$(cd "$(dirname "$0")" && pwd)
venv=${1:-$here/.venv}
src=$venv/src/gerbonara

PR15=7446168d730ec5865a5a99fbb79b1accfd3e51b8  # Draw KiCad schematic text like KiCad (with PRs 11-14 below it)
PR16=2fd5cbb05a77996832172d27ec57be1bdf331759  # Fix parsing of Excellon tool definitions with feed rate and spindle speed

python3 -m venv "$venv"
if [ ! -d "$src/.git" ]; then
    git clone --quiet https://github.com/jaseg/gerbonara "$src"
fi
git -C "$src" fetch --quiet origin pull/15/head pull/16/head
git -C "$src" checkout --quiet --detach "$PR15"
git -C "$src" -c user.name=kicad10_compat -c user.email=kicad10_compat@localhost merge --quiet --no-edit "$PR16"
"$venv/bin/pip" install --quiet "$src" pillow pytest
echo "Installed gerbonara $(git -C "$src" rev-parse --short HEAD) into $venv"
