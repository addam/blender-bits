"""Animate: an Empty walks the flattened path at constant speed (motion preview).

See design *Animate*. This is a motion preview, not a time-accurate sim -- the
single print speed drives both strokes and travels, so per-move feedrates are
ignored. Arc-length frame spacing (from flatten.sample_path) plus LINEAR
location interpolation makes velocity constant everywhere; default Bezier would
ease at every vertex and break that.

Locations are baked world-space, so one Empty covers every object. An optional
``extruding`` custom property (0/1, CONSTANT interp) tracks pen-up vs pen-down.
Re-running reuses the same Empty and clears its old keyframes, so it is
idempotent and never piles up duplicates.
"""

import bpy
from bpy.types import Operator

from . import generate
from . import flatten

HEAD_NAME = "SpaghettiHead"


def _get_head(context):
    """Reuse the SpaghettiHead empty (idempotent re-run) or create it."""
    obj = bpy.data.objects.get(HEAD_NAME)
    if obj is not None and obj.type == "EMPTY":
        obj.animation_data_clear()  # drop prior keyframes; do not stack
        return obj
    empty = bpy.data.objects.new(HEAD_NAME, None)
    empty.empty_display_type = "SPHERE"
    context.scene.collection.objects.link(empty)
    return empty


def _fcurves(obj):
    """F-curves of obj's action, across slotted (4.4+) and legacy actions."""
    adt = obj.animation_data
    if adt is None or adt.action is None:
        return []
    action = adt.action
    slot = getattr(adt, "action_slot", None)
    if slot is not None and hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                cbag = strip.channelbag(slot)
                if cbag is not None:
                    return cbag.fcurves
    return getattr(action, "fcurves", [])


class SPAGHETTI_OT_animate(Operator):
    """Animate an Empty walking the toolpath at constant speed (motion preview)"""
    bl_idname = "print_spaghetti.animate"
    bl_label = "Animate Toolpath"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.print_spaghetti
        objects = generate.target_objects(context)
        if not objects:
            self.report({"ERROR"}, "No mesh objects to animate")
            return {"CANCELLED"}

        sequences, skipped = generate.read_objects(objects, settings)
        if not sequences:
            self.report({"ERROR"},
                        "No literal (verts+edges) geometry found to animate")
            return {"CANCELLED"}

        moves = flatten.flatten_moves(sequences)
        scene = context.scene
        render = scene.render
        fps = render.fps / render.fps_base  # effective (base handles 29.97 etc.)
        samples = flatten.sample_path(
            moves, settings.print_speed, fps, scene.frame_start)

        head = _get_head(context)
        for frame, pos, extruding in samples:
            head.location = pos
            head["extruding"] = 1.0 if extruding else 0.0
            head.keyframe_insert(data_path="location", frame=frame)
            head.keyframe_insert(data_path='["extruding"]', frame=frame)

        for fc in _fcurves(head):
            constant = fc.data_path == '["extruding"]'
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT" if constant else "LINEAR"

        last_frame = samples[-1][0]
        scene.frame_end = last_frame

        msg = "Animated {} object(s), {} moves; frames {}-{}".format(
            len(sequences), len(moves), scene.frame_start, last_frame)
        if skipped:
            msg += "; skipped {} recipe(s) with faces".format(len(skipped))
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def register():
    bpy.utils.register_class(SPAGHETTI_OT_animate)


def unregister():
    bpy.utils.unregister_class(SPAGHETTI_OT_animate)
