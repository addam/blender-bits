"""moves_to_gcode: flattened move list -> Marlin G-code text.

Follows gcode-notes.md: ``G90`` absolute XYZ + ``M83`` relative E; Z comes from
geometry; the stadium cross-section drives per-segment E; output is modal (emit
F and only the axes that change). Retraction is deliberately skipped for this
first experiment (notes section 1: "quality, not correctness").

``moves_to_gcode`` returns ``(text, stats)`` where ``stats`` holds the estimated
print time (minutes, motion only -- start/end heating waits are indeterminate)
and filament consumption (metres of stock). Both are also written as header
comments in the G-code, the way a slicer does.
"""

import math


def _fmt(value, decimals):
    """ASCII fixed-point, trailing zeros trimmed. '-0' collapses to '0'."""
    s = "{:.{}f}".format(value, decimals)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def stadium_area(width, height):
    """PrusaSlicer bead cross-section: rectangle + semicircular caps (mm^2)."""
    return (width - height) * height + math.pi * (height / 2.0) ** 2


def segment_extrusion(seg_len, width, height, filament_diameter):
    """mm of filament for one segment (M83 relative-E delta)."""
    filament_area = math.pi * (filament_diameter / 2.0) ** 2
    return stadium_area(width, height) * seg_len / filament_area


DEFAULT_START_GCODE = """\
; print_spaghetti default start (Ender 3 / Marlin)
G90 ; absolute XYZ
M83 ; relative E
M140 S{bed} ; set bed temp
M104 S{nozzle} ; set nozzle temp
M190 S{bed} ; wait for bed
M109 S{nozzle} ; wait for nozzle
G28 ; home all axes
G92 E0
G1 Z2.0 F3000 ; lift
G1 X2.0 Y10 F3000
G1 Z0.28 F240
G1 X2.0 Y140 E10 F1500 ; prime line
G1 X2.3 Y140 F5000
G1 X2.3 Y10 E10 F1200 ; prime line
G92 E0
M107 ; fan off
"""

DEFAULT_END_GCODE = """\
; print_spaghetti default end
M104 S0 ; nozzle off
M140 S0 ; bed off
M107 ; fan off
G91 ; relative
G1 Z10 F600 ; lift
G90 ; absolute
G1 X5 Y200 F3000 ; present
M84 X Y E ; disable motors
"""


def _resolve_text(datablock, default, nozzle, bed):
    if datablock is not None:
        return datablock.as_string()
    return default.format(nozzle=_fmt(nozzle, 0), bed=_fmt(bed, 0))


def moves_to_gcode(moves, settings):
    """Render the flattened move list to a full G-code document string."""
    start = _resolve_text(settings.start_gcode, DEFAULT_START_GCODE,
                          settings.nozzle_temp, settings.bed_temp)
    end = _resolve_text(settings.end_gcode, DEFAULT_END_GCODE,
                        settings.nozzle_temp, settings.bed_temp)

    print_f = settings.print_speed * 60.0    # mm/s -> mm/min
    travel_f = settings.travel_speed * 60.0
    filament_d = settings.filament_diameter

    body = []
    total_e_mm = 0.0       # relative-E deltas summed = filament length (mm)
    total_time_s = 0.0     # motion time only (start/end waits excluded)

    # Modal state carried across moves.
    last = None            # previous (x, y, z)
    cur_f = None           # last emitted feedrate

    for i, mv in enumerate(moves):
        p = mv["pos"]
        x, y, z = p.x, p.y, p.z
        extruding = mv["extruding"] and last is not None

        # Which positional axes changed (3 decimals ~ 1 micron).
        axes = []
        if last is None or round(x, 3) != round(last[0], 3):
            axes.append("X" + _fmt(x, 3))
        if last is None or round(y, 3) != round(last[1], 3):
            axes.append("Y" + _fmt(y, 3))
        if last is None or round(z, 3) != round(last[2], 3):
            axes.append("Z" + _fmt(z, 3))

        if not axes and last is not None:
            continue  # coincident point; nothing to move

        feed = print_f if extruding else travel_f
        parts = []
        seg_len = math.dist((x, y, z), last) if last is not None else 0.0

        if extruding:
            e = segment_extrusion(seg_len, mv["w"], mv["h"], filament_d)
            total_e_mm += e
            parts.append("G1")
            parts.extend(axes)
            parts.append("E" + _fmt(e, 5))
        else:
            # Travel (also the initial approach and per-object hops).
            parts.append("G0")
            parts.extend(axes)

        speed = settings.print_speed if extruding else settings.travel_speed
        if speed > 0.0:
            total_time_s += seg_len / speed

        if round(feed, 3) != (round(cur_f, 3) if cur_f is not None else None):
            parts.append("F" + _fmt(feed, 0))
            cur_f = feed

        body.append(" ".join(parts))
        last = (x, y, z)

    stats = {
        "time_min": total_time_s / 60.0,
        "filament_m": total_e_mm / 1000.0,   # mm of 1.75 stock -> metres
    }

    out = [start.rstrip("\n")]
    out.append("; estimated printing time (motion only) = {} min".format(
        _fmt(stats["time_min"], 1)))
    out.append("; filament used = {} m ({} mm dia)".format(
        _fmt(stats["filament_m"], 3), _fmt(filament_d, 2)))
    out.append("; --- print_spaghetti toolpath ---")
    out.extend(body)
    out.append("; --- end toolpath ---")
    out.append(end.rstrip("\n"))
    return "\n".join(out) + "\n", stats
