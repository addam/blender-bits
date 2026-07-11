"""N-panel ("Spaghetti" tab) + Export operator + File > Export menu entry.

Minimum surface for the edges/guide-verts experiment: settings, an object count
readout, and one Export G-code button. Materialize / animate / collide / fix are
deferred.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper

from . import generate
from . import flatten
from . import gcode
from . import animate


class SPAGHETTI_OT_export_gcode(Operator, ExportHelper):
    """Export selected mesh objects (edges + guide verts) to G-code"""
    bl_idname = "print_spaghetti.export_gcode"
    bl_label = "Export G-code"
    bl_options = {"REGISTER"}

    filename_ext = ".gcode"
    filter_glob: StringProperty(default="*.gcode", options={"HIDDEN"})

    def execute(self, context):
        settings = context.scene.print_spaghetti
        objects = generate.target_objects(context)
        if not objects:
            self.report({"ERROR"}, "No mesh objects to export")
            return {"CANCELLED"}

        sequences, skipped = generate.read_objects(objects, settings)
        if not sequences:
            self.report({"ERROR"},
                        "No literal (verts+edges) geometry found to export")
            return {"CANCELLED"}

        moves = flatten.flatten_moves(sequences)
        text, stats = gcode.moves_to_gcode(moves, settings)

        with open(self.filepath, "w") as f:
            f.write(text)

        msg = "Exported {} object(s), {} moves; ~{:.1f} min, {:.3f} m filament".format(
            len(sequences), len(moves), stats["time_min"], stats["filament_m"])
        if skipped:
            msg += "; skipped {} recipe(s) with faces: {}".format(
                len(skipped), ", ".join(skipped))
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SPAGHETTI_PT_panel(Panel):
    bl_label = "Print Spaghetti"
    bl_idname = "SPAGHETTI_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Spaghetti"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.print_spaghetti

        col = layout.column(align=True)
        col.prop(settings, "line_width")
        col.prop(settings, "layer_height")
        col.prop(settings, "filament_diameter")

        col = layout.column(align=True)
        col.prop(settings, "print_speed")
        col.prop(settings, "travel_speed")

        col = layout.column(align=True)
        col.prop(settings, "nozzle_temp")
        col.prop(settings, "bed_temp")

        col = layout.column(align=True)
        col.prop(settings, "start_gcode")
        col.prop(settings, "end_gcode")

        n = len(generate.target_objects(context))
        layout.label(text="{} mesh object(s) targeted".format(n))
        layout.operator(animate.SPAGHETTI_OT_animate.bl_idname,
                        icon="PLAY")
        layout.operator(SPAGHETTI_OT_export_gcode.bl_idname,
                        icon="EXPORT")


def _menu_export(self, context):
    self.layout.operator(SPAGHETTI_OT_export_gcode.bl_idname,
                         text="Print Spaghetti G-code (.gcode)")


_classes = (SPAGHETTI_OT_export_gcode, SPAGHETTI_PT_panel)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
