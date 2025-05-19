bl_info = {
    "name": "Snap Bisect",
    "blender": (2, 42, 0),
    "category": "Mesh",
}

import bpy
import gpu
import bmesh
from bpy.props import BoolProperty, FloatProperty
from mathutils import Vector
from mathutils.geometry import normal
from gpu_extras.batch import batch_for_shader
import numpy as np


def is_view_transparent(context):
    shading = context.space_data.shading
    return shading.show_xray_wireframe if shading.type == 'WIREFRAME' else shading.show_xray


def is_view_perspective(context):
    return context.space_data.region_3d.view_perspective == 'PERSP'


def camera_center(matrix):
    result = matrix.inverted() @ Vector((0, 0, 0, 1))
    return result.xyz / result.w


def ortho_axis(matrix):
    return matrix.row[2].to_3d()


def draw_points(points, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'POINTS', {"pos": points})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def create_callback():
    def draw_callback(self, context):
        alpha = 0.5 if is_view_transparent(context) else 1.0
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.blend_set('ALPHA')
        draw_points(draw_callback.points, (1.0, 0.0, 1.0, alpha))
        draw_points(draw_callback.marked_points, (1.0, 1.0, 0.0, 1.0))
        gpu.state.depth_test_set('ALWAYS')
        draw_points(draw_callback.marked_points, (1.0, 1.0, 0.0, 0.5))
    draw_callback.points = []
    draw_callback.marked_points = []
    return draw_callback


class SnapBisect(bpy.types.Operator):
    """Bisect operator with snapping to vertices or edge midpoints"""
    bl_idname = "mesh.snap_bisect"
    bl_label = "Snap Bisect"
    bl_options = {'REGISTER', 'UNDO'}
    offset: FloatProperty(name="Offset", description="Distance from the given points", unit='LENGTH')
    use_fill: BoolProperty(name="Fill", description="Fill in the cut")
    show_hidden: BoolProperty(name="Show Hidden", description="Show hidden vertices", options={'HIDDEN'})
    clear_inner: BoolProperty(name="Clear Inner", description="Remove geometry behind the plane")
    clear_outer: BoolProperty(name="Clear Inner", description="Remove geometry in front of the plane")

    points: list  # picked points
    anchors: np.ndarray  # points available for picking
    draw_callback: object  # redraw function
    handle: object

    def pick(self, context, event):
        """Find the clicked point among self.anchors.
        returns: clicked anchor, in world coordinates"""
        max_distance = 10
        sce = context.scene
        depsgraph = context.view_layer.depsgraph
        mouse_position = Vector((event.mouse_region_x, event.mouse_region_y))
        if is_view_perspective(context):
            origin = camera_center(context.space_data.region_3d.view_matrix)
            direction = None
        else:
            origin = None
            direction = ortho_axis(context.space_data.region_3d.view_matrix)

        def visible(v, dr=direction):
            if origin is not None:
                dr = v[:3] - origin
            is_hit, *_ = sce.ray_cast(depsgraph, origin, dr, distance=np.sum(dr**2)**0.5 - 1e-5)
            return not is_hit

        distances, points = distances_2d(self.anchors, mouse_position, context, max_distance)
        if not distances.any():
            return None
        candidate = points[:, np.argmin(distances)]
        # the following code is optimized to only call `visible` when necessary
        if self.not_picked(candidate) and (is_view_transparent(context) or visible(candidate)):
            return candidate
        for candidate in points[:, np.argsort(distances)].T:
            if self.not_picked(candidate) and visible(candidate):
                return candidate

    def not_picked(self, nparray):
        return not any(np.allclose(nparray, p) for p in self.points)

    def reset_points(self):
        """Find available anchor points and also store them for drawing"""
        bm = self.bmesh
        tsf = self.matrix_world
        midpoints = [tsf @ ((e.verts[0].co + e.verts[1].co) * 0.5) for e in bm.edges if not e.hide]
        if self.show_hidden:
            midpoints += [tsf @ v.co for v in bm.verts if v.hide]
        anchors = [tsf @ v.co for v in bm.verts if not v.hide] + midpoints
        self.anchors = np.array([v.to_4d() for v in anchors]).T
        self.draw_callback.points = [tuple(co) for co in midpoints]

    def set_header_text(self, context, do_unset=False):
        text = (
            None if do_unset
            else f"LMB: mark cut point, H: show hidden ({self.show_hidden})"
            + (
                "" if len(self.points) == 0
                else ", X/Y/Z: plane-aligned cut" if len(self.points) == 1
                else ", X/Y/Z: axis-aligned cut, Enter/Space: view-aligned cut"
            )
        )
        context.area.header_text_set(text)

    def modal(self, context, event):
        context.window.cursor_modal_set('KNIFE')
        if event.type in {'RIGHTMOUSE', 'ESC'} or not self.bmesh.is_valid:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
            context.region.tag_redraw()
            self.set_header_text(context, True)
            context.window.cursor_modal_restore()
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            point = self.pick(context, event)
            if point is not None:
                self.points.append(point)
                self.draw_callback.marked_points.append(tuple(point))
                context.region.tag_redraw()
                self.set_header_text(context)
        elif event.type in {'RET', 'SPACE', 'NUMPAD_ENTER'}:
            if len(self.points) == 2:
                mat = context.space_data.region_3d.view_matrix
                self.points.append(
                    camera_center(mat) if is_view_perspective(context)
                    else Vector(self.points[0]) + ortho_axis(mat)
                )
        elif event.type in {'X', 'Y', 'Z'} and self.points:
            origin = self.points[0]
            offset = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
            if len(self.points) == 1:
                self.points.append(origin + offset["ZXY".index(event.type)])
                self.points.append(origin + offset["YZX".index(event.type)])
            if len(self.points) == 2:
                self.points.append(origin + offset["XYZ".index(event.type)])
        elif event.type == 'H' and event.value == 'PRESS':
            self.show_hidden = not self.show_hidden
            self.reset_points()
            self.set_header_text(context)
            context.region.tag_redraw()
        else:
            return {'PASS_THROUGH'}
        if len(self.points) >= 3:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
            context.window.cursor_modal_restore()
            return self.execute(context)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        self.set_header_text(context, True)
        nor = normal(self.points[:3])
        if nor.length_squared == 0:
            self.report(type={'ERROR_INVALID_INPUT'}, message="Selected points are collinear")
            return {'CANCELLED'}
        co = self.points[-1] + nor * self.offset
        bpy.ops.mesh.bisect(
            plane_co=co,
            plane_no=nor,
            use_fill=self.use_fill,
            clear_inner=self.clear_inner,
            clear_outer=self.clear_outer
        )
        return {'FINISHED'}

    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'VIEW_3D' and context.mode == 'EDIT_MESH'

    def invoke(self, context, _event):
        self.points = []
        self.bmesh = bmesh.from_edit_mesh(context.edit_object.data)
        if not any(e.select for e in self.bmesh.edges):
            self.report(type={'ERROR_INVALID_INPUT'}, message="Selected edges/faces required")
            return {'CANCELLED'}
        self.matrix_world = context.edit_object.matrix_world
        self.draw_callback = create_callback()
        self.reset_points()
        self.handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, (self, context), 'WINDOW', 'POST_VIEW'
        )
        context.region.tag_redraw()
        context.window_manager.modal_handler_add(self)
        self.set_header_text(context)
        return {'RUNNING_MODAL'}


def menu_func(self, _context):
    self.layout.operator(SnapBisect.bl_idname)


# adopted from bpy_extras.view3d_utils
def distances_2d(points, origin, context, max_distance=float("inf")):
    """Find 3D points around an origin point as seen on-screen
    points: np.array with 4D points in columns
    origin: 2D point, origin for distance computation
    context: bpy.context
    max_distance: only return points up to this distance
    returns: squared distances (np.array) and 3D points (np.array)
    """
    region = context.region
    rv3d = context.space_data.region_3d
    w = region.width / 2.0
    h = region.height / 2.0
    x, y = origin
    persp = np.array(rv3d.perspective_matrix)
    screen = np.array(((w, 0, 0, w - x), (0, h, 0, h - y), (0, 0, 1, 0), (0, 0, 0, 1)))
    projected = (screen @ persp) @ points
    distances_squared = np.sum((projected[:2, :] / projected[3:, :])**2, axis=0)
    valid = (distances_squared <= max_distance**2) & (projected[3, :] > 0)
    return distances_squared[valid], points[:3, valid]


def register():
    bpy.utils.register_class(SnapBisect)
    bpy.types.VIEW3D_MT_edit_mesh.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh.remove(menu_func)
    bpy.utils.unregister_class(SnapBisect)


if __name__ == "__main__":
    register()
