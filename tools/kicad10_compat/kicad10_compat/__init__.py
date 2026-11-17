"""Convert KiCad 10.99 (development version) projects to files KiCad 10.0 can read."""

from .common import ConversionError, Report
from .board import convert_board
from .schematic import convert_schematic
from .project import convert_project

EXTENSIONS = ('.kicad_pro', '.kicad_pcb', '.kicad_sch', '.kicad_sym', '.kicad_mod')
