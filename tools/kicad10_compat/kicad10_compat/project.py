"""Convert KiCad 10.99 project files (.kicad_pro) to KiCad 10.

Project files are JSON. Each section has its own schema version, and KiCad migrates them up one version at a time.
This undoes the migrations KiCad 10.99 added on top of KiCad 10.0.
"""

import json
import re

from .common import ConversionError, Report

# Schema versions of KiCad 10.0.x and of KiCad master as of 2026-11-13
PROJECT_SCHEMA = (3, 4)          # common/project/project_file.cpp
BOARD_SETTINGS_SCHEMA = (2, 4)   # pcbnew/board_design_settings.cpp
ERC_SCHEMA = (0, 1)              # eeschema/erc/erc_settings.cpp
TUNING_SCHEMA = (0, 2)           # common/project/tuning_profiles.cpp


# DRC error codes of KiCad 10.0.x and their settings keys (pcbnew/drc/drc_item.cpp)
KICAD10_DRC_KEYS = {
    'DRCE_UNCONNECTED_ITEMS': 'unconnected_items', 'DRCE_SHORTING_ITEMS': 'shorting_items',
    'DRCE_ALLOWED_ITEMS': 'items_not_allowed', 'DRCE_TEXT_ON_EDGECUTS': 'text_on_edge_cuts',
    'DRCE_CLEARANCE': 'clearance', 'DRCE_CREEPAGE': 'creepage', 'DRCE_TRACKS_CROSSING': 'tracks_crossing',
    'DRCE_EDGE_CLEARANCE': 'copper_edge_clearance', 'DRCE_ZONES_INTERSECT': 'zones_intersect',
    'DRCE_ISOLATED_COPPER': 'isolated_copper', 'DRCE_STARVED_THERMAL': 'starved_thermal',
    'DRCE_DANGLING_VIA': 'via_dangling', 'DRCE_DANGLING_TRACK': 'track_dangling',
    'DRCE_HOLE_CLEARANCE': 'hole_clearance', 'DRCE_DRILLED_HOLES_TOO_CLOSE': 'hole_to_hole',
    'DRCE_DRILLED_HOLES_COLOCATED': 'holes_co_located', 'DRCE_CONNECTION_WIDTH': 'connection_width',
    'DRCE_TRACK_WIDTH': 'track_width', 'DRCE_TRACK_ANGLE': 'track_angle',
    'DRCE_TRACK_SEGMENT_LENGTH': 'track_segment_length', 'DRCE_ANNULAR_WIDTH': 'annular_width',
    'DRCE_DRILL_OUT_OF_RANGE': 'drill_out_of_range', 'DRCE_VIA_DIAMETER': 'via_diameter',
    'DRCE_PADSTACK': 'padstack', 'DRCE_PADSTACK_INVALID': 'padstack_invalid',
    'DRCE_MICROVIA_DRILL_OUT_OF_RANGE': 'microvia_drill_out_of_range',
    'DRCE_OVERLAPPING_FOOTPRINTS': 'courtyards_overlap', 'DRCE_MISSING_COURTYARD': 'missing_courtyard',
    'DRCE_MALFORMED_COURTYARD': 'malformed_courtyard', 'DRCE_PTH_IN_COURTYARD': 'pth_inside_courtyard',
    'DRCE_NPTH_IN_COURTYARD': 'npth_inside_courtyard', 'DRCE_DISABLED_LAYER_ITEM': 'item_on_disabled_layer',
    'DRCE_INVALID_OUTLINE': 'invalid_outline', 'DRCE_DUPLICATE_FOOTPRINT': 'duplicate_footprints',
    'DRCE_MISSING_FOOTPRINT': 'missing_footprint', 'DRCE_EXTRA_FOOTPRINT': 'extra_footprint',
    'DRCE_NET_CONFLICT': 'net_conflict', 'DRCE_SCHEMATIC_PARITY': 'footprint_symbol_mismatch',
    'DRCE_FOOTPRINT_FILTERS': 'footprint_filters_mismatch',
    'DRCE_SCHEMATIC_FIELDS_PARITY': 'footprint_symbol_field_mismatch',
    'DRCE_LIB_FOOTPRINT_ISSUES': 'lib_footprint_issues', 'DRCE_LIB_FOOTPRINT_MISMATCH': 'lib_footprint_mismatch',
    'DRCE_UNRESOLVED_VARIABLE': 'unresolved_variable', 'DRCE_ASSERTION_FAILURE': 'assertion_failure',
    'DRCE_GENERIC_WARNING': 'generic_warning', 'DRCE_GENERIC_ERROR': 'generic_error',
    'DRCE_COPPER_SLIVER': 'copper_sliver', 'DRCE_SOLDERMASK_BRIDGE': 'solder_mask_bridge',
    'DRCE_SILK_MASK_CLEARANCE': 'silk_over_copper', 'DRCE_SILK_EDGE_CLEARANCE': 'silk_edge_clearance',
    'DRCE_SILK_CLEARANCE': 'silk_overlap', 'DRCE_TEXT_HEIGHT': 'text_height',
    'DRCE_TEXT_THICKNESS': 'text_thickness', 'DRCE_LENGTH_OUT_OF_RANGE': 'length_out_of_range',
    'DRCE_SKEW_OUT_OF_RANGE': 'skew_out_of_range', 'DRCE_VIA_COUNT_OUT_OF_RANGE': 'too_many_vias',
    'DRCE_DIFF_PAIR_GAP_OUT_OF_RANGE': 'diff_pair_gap_out_of_range',
    'DRCE_DIFF_PAIR_UNCOUPLED_LENGTH_TOO_LONG': 'diff_pair_uncoupled_length_too_long', 'DRCE_FOOTPRINT': 'footprint',
    'DRCE_FOOTPRINT_TYPE_MISMATCH': 'footprint_type_mismatch',
    'DRCE_PAD_TH_WITH_NO_HOLE': 'through_hole_pad_without_hole',
    'DRCE_MIRRORED_TEXT_ON_FRONT_LAYER': 'mirrored_text_on_front_layer',
    'DRCE_NONMIRRORED_TEXT_ON_BACK_LAYER': 'nonmirrored_text_on_back_layer',
    'DRCE_MISSING_TUNING_PROFILE': 'missing_tuning_profile',
    'DRCE_TUNING_PROFILE_IMPLICIT_RULES': 'tuning_profile_track_geometries',
    'DRCE_TRACK_ON_POST_MACHINED_LAYER': 'track_on_post_machined_layer',
    'DRCE_TRACK_NOT_CENTERED_ON_VIA': 'track_not_centered_on_via',
}

# KiCad's marker type enum (include/marker_base.h) and its API names
MARKER_TYPES = {'MT_UNKNOWN': 0, 'MT_ERC': 1, 'MT_DRC': 2, 'MT_DRAWING_SHEET': 3, 'MT_RATSNEST': 4, 'MT_PARITY': 5,
                'MT_SIMULATION': 6}

NIL_UUID = '00000000-0000-0000-0000-000000000000'


# KiCad 10's marker strings use LayerName() (common/layer_id.cpp), which differs from the canonical layer names of
# board files for these layers
LAYER_DISPLAY_NAMES = {
    'B_Adhes': 'B.Adhesive', 'F_Adhes': 'F.Adhesive', 'B_SilkS': 'B.Silkscreen', 'F_SilkS': 'F.Silkscreen',
    'Dwgs_User': 'User.Drawings', 'Cmts_User': 'User.Comments', 'Eco1_User': 'User.Eco1', 'Eco2_User': 'User.Eco2',
    'F_CrtYd': 'F.Courtyard', 'B_CrtYd': 'B.Courtyard',
}


def api_layer_name(name):
    """ BL_F_Cu -> F.Cu, BL_In1_Cu -> In1.Cu, BL_F_SilkS -> F.Silkscreen, BL_User_1 -> User.1 """
    if not name or not name.startswith('BL_'):
        return 'F.Cu'
    name = name[3:]
    return LAYER_DISPLAY_NAMES.get(name, name.replace('_', '.', 1))


def drc_exclusion_to_legacy(entry, report):
    """ Convert one ProtoJSON DRC exclusion of KiCad 10.99 to KiCad 10's [marker string, comment] """
    marker = entry.get('marker', {})
    error_type = marker.get('error_type', '')
    # The API names are the KiCad 10 error code names with another prefix. 10.99 renamed text_thickness to line_width,
    # which now also checks silkscreen graphics.
    code = 'DRCE_' + error_type[len('DRCET_'):]
    if code == 'DRCE_LINE_WIDTH':
        code = 'DRCE_TEXT_THICKNESS'
    key = KICAD10_DRC_KEYS.get(code)
    if key is None:
        report.warn(f'DRC exclusion for {error_type}, which KiCad 10 does not have, was dropped')
        return None

    pos = marker.get('position', {})
    x, y = int(pos.get('x_nm', 0)), int(pos.get('y_nm', 0))
    items = [i.get('value', NIL_UUID) for i in marker.get('items', [])] + [NIL_UUID, NIL_UUID]
    main, aux = items[0], items[1]
    layer = api_layer_name(marker.get('layer'))

    # Same formats as PCB_MARKER::SerializeToString() of KiCad 10
    if code in ('DRCE_COPPER_SLIVER', 'DRCE_GENERIC_WARNING', 'DRCE_GENERIC_ERROR'):
        s = f'{key}|{x}|{y}|{main}|{layer}'
    elif code == 'DRCE_UNCONNECTED_ITEMS':
        s = f'{key}|{x}|{y}|{layer}|{MARKER_TYPES.get(marker.get("marker_type"), 2)}|{main}|{aux}'
    elif code == 'DRCE_STARVED_THERMAL':
        s = f'{key}|{x}|{y}|{main}|{aux}|{layer}'
    elif code == 'DRCE_UNRESOLVED_VARIABLE' and marker.get('marker_type') == 'MT_DRAWING_SHEET':
        s = f'{key}|{x}|{y}||'
    else:
        s = f'{key}|{x}|{y}|{main}|{aux}'
    return [s, entry.get('comment', '')]


def convert_project(text, path='<project>', force=False):
    report = Report(path)
    data = json.loads(text)
    meta = data.setdefault('meta', {})
    version = meta.get('version', 0)
    if version > PROJECT_SCHEMA[1] and not force:
        raise ConversionError(f'{path}: project schema version {version} is newer than the newest one this converter '
                              f'knows ({PROJECT_SCHEMA[1]}). Use --force to convert it anyway.')
    if version > PROJECT_SCHEMA[0]:
        # 3 -> 4 only cleaned up empty bus alias tables, which KiCad 10 reads either way
        meta['version'] = PROJECT_SCHEMA[0]
        report.count('project schema version')

    bds = data.get('board', {}).get('design_settings')
    if bds is not None and (v := bds.get('meta', {}).get('version', 0)) > BOARD_SETTINGS_SCHEMA[0]:
        if v >= 4:
            # 3 -> 4 renamed text_thickness to line_width. The new key wins over a stale old one.
            for section, old, new in (('rule_severities', 'text_thickness', 'line_width'),
                                      ('rules', 'min_text_thickness', 'min_silk_line_width')):
                sec = bds.get(section)
                if isinstance(sec, dict) and new in sec:
                    sec[old] = sec.pop(new)
                    report.count('renamed DRC settings')
        if v >= 3:
            # 2 -> 3 turned DRC exclusions from marker strings into ProtoJSON
            excl = []
            for entry in bds.get('drc_exclusions', []):
                if isinstance(entry, dict):
                    if (legacy := drc_exclusion_to_legacy(entry, report)) is not None:
                        excl.append(legacy)
                        report.count('DRC exclusions converted')
                else:
                    excl.append(entry)
            bds['drc_exclusions'] = excl
        bds['meta']['version'] = BOARD_SETTINGS_SCHEMA[0]
        report.count('board settings schema version')

    erc = data.get('erc')
    if erc is not None and erc.get('meta', {}).get('version', 0) > ERC_SCHEMA[0]:
        # 0 -> 1 turned ERC exclusions from marker strings into ProtoJSON
        kept = [e for e in erc.get('erc_exclusions', []) if not isinstance(e, dict)]
        if dropped := len(erc.get('erc_exclusions', [])) - len(kept):
            report.warn(f'{dropped} ERC exclusions in the new format were dropped, re-create them in KiCad 10')
        erc['erc_exclusions'] = kept
        erc['meta']['version'] = ERC_SCHEMA[0]
        report.count('ERC settings schema version')

    tuning = data.get('tuning_profiles')
    if tuning is not None and (v := tuning.get('meta', {}).get('version', 0)) > TUNING_SCHEMA[0]:
        for profile in tuning.get('tuning_profiles_impedance_geometric', []):
            if v >= 2:
                profile.pop('net_chain_bridge_prop_delay', None)
            if v >= 1:
                profile.pop('frequency', None)
                profile.pop('model_solder_mask', None)
        tuning['meta']['version'] = TUNING_SCHEMA[0]
        report.count('tuning profile schema version')

    # KiCad writes two-space indented JSON with a trailing newline
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n', report
