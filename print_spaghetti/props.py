"""Scene-level printer settings (PrinterSettings PropertyGroup).

Minimum set needed to export edges (extruding strokes) and guide vertices
(travel waypoints) to G-code. Per-object / per-vertex overrides described in
design.md are deferred; only the global fallbacks live here.

Start/end G-code are optional references to Text datablocks copied verbatim per
printer (design *G-code export*). When unset, gcode.py emits a built-in Ender 3
/ Marlin default parameterised by the temperatures below.
"""

import bpy
from bpy.props import FloatProperty, PointerProperty
from bpy.types import PropertyGroup


class PrinterSettings(PropertyGroup):
    filament_diameter: FloatProperty(
        name="Filament Diameter",
        description="Filament stock diameter (mm); denominator of the E volume math",
        default=1.75, min=0.1, soft_max=5.0, unit="LENGTH",
    )
    line_width: FloatProperty(
        name="Line Width",
        description="Bead width (mm) fallback for verts with no Skin radius",
        default=0.4, min=0.01, soft_max=2.0, unit="LENGTH",
    )
    layer_height: FloatProperty(
        name="Layer Height",
        description="Bead height (mm) fallback for verts with no Skin radius",
        default=0.2, min=0.01, soft_max=2.0, unit="LENGTH",
    )
    print_speed: FloatProperty(
        name="Print Speed",
        description="Feedrate for extruding moves (mm/s)",
        default=20.0, min=1.0, soft_max=200.0,
    )
    travel_speed: FloatProperty(
        name="Travel Speed",
        description="Feedrate for non-extruding travel moves (mm/s)",
        default=120.0, min=1.0, soft_max=400.0,
    )
    nozzle_temp: FloatProperty(
        name="Nozzle Temp",
        description="Hotend temperature (C) for the default start G-code",
        default=210.0, min=0.0, soft_max=350.0,
    )
    bed_temp: FloatProperty(
        name="Bed Temp",
        description="Bed temperature (C) for the default start G-code",
        default=60.0, min=0.0, soft_max=150.0,
    )
    start_gcode: PointerProperty(
        name="Start G-code",
        description="Text datablock copied verbatim before the toolpath "
                    "(homing/heating/prime). Empty = built-in Ender 3 default",
        type=bpy.types.Text,
    )
    end_gcode: PointerProperty(
        name="End G-code",
        description="Text datablock copied verbatim after the toolpath "
                    "(cooldown/park). Empty = built-in default",
        type=bpy.types.Text,
    )


def register():
    bpy.utils.register_class(PrinterSettings)
    bpy.types.Scene.print_spaghetti = PointerProperty(type=PrinterSettings)


def unregister():
    del bpy.types.Scene.print_spaghetti
    bpy.utils.unregister_class(PrinterSettings)
