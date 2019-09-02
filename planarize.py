bl_info = {
    "name": "Planarize",
    "author": "Addam Dominec",
    "version": (0, 3),
    "blender": (2, 80, 0),
    "location": "Mesh -> Planarize",
    "warning": "",
    "description": "Flatten all polygon faces",
    "category": "Mesh",
    "wiki_url": "",
    "tracker_url": ""
}


import bpy
import numpy
import mathutils
import random
from collections import defaultdict


def get_smoothened_normals(faces):
    incidence = defaultdict(list)
    for face in faces:
        for vertex in face.vertices:
            incidence[vertex].append(face)
    neighbors = dict()
    for face in faces:
        neighbors[face] = [other for vertex in face.vertices for other in incidence[vertex] if other is not face]
    normals = {face: face.normal for face in faces}
    randfaces = [face for face in faces if len(neighbors[face]) >= 3]
    for iteration in range(5):
        random.shuffle(randfaces)
        for face in randfaces:
            nor = normals[face]
            nearest = [normals[neighbor] for neighbor in neighbors[face]]
            nearest.sort(key=lambda other_normal: (other_normal - nor).length_squared)
            normals[face] = sum(nearest[:3], mathutils.Vector((0, 0, 0))).normalized()
    return normals


def planarize(vertices, orig_coords, faces, normals, rigidity=1.0):
    planes = defaultdict(list)
    for face in faces:
        if len(face.vertices) == 3:
            continue
        plane_pair = normals[face], normals[face].dot(face.center)
        for vertex_index in face.vertices:
            planes[vertex_index].append(plane_pair)
    for vertex in vertices:
        alpha = rigidity if len(planes[vertex.index]) >= 3 else max(rigidity, 1e-3)
        A = (alpha * numpy.eye(3)).tolist()
        b = list(alpha * orig_coords[vertex])
        for (nor, plane_c) in planes[vertex.index]:
            A.append(nor)
            b.append(plane_c)
        coords, residuals, rank, singular = numpy.linalg.lstsq(A, b)
        vertex.co = coords


class Planarize(bpy.types.Operator):
    """Flattens all polygons of the active mesh"""
    bl_idname = "mesh.planarize"
    bl_label = "Planarize"
    bl_options = {'REGISTER', 'UNDO'}
    rigidity = bpy.props.FloatProperty(name="Rigidity",
        description="Slows down the planarization effect", default=1, min=0)
    iterations = bpy.props.IntProperty(name="Steps",
        description="Repeats the calculation to get a better result", default=2, min=1)
    do_smoothen = bpy.props.BoolProperty(name="Smoothen Normals",
        description="Distributes normals evenly across the surface", default=True)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        recall_mode = context.object.mode
        bpy.ops.object.mode_set(mode='OBJECT')

        mesh = context.active_object.data
        orig_coords = {vertex: vertex.co for vertex in mesh.vertices}
        normals = {face: face.normal for face in mesh.polygons}
        for iteration in range(self.iterations):
            if self.do_smoothen:
                normals = get_smoothened_normals(mesh.polygons)
            planarize(mesh.vertices, orig_coords, mesh.polygons, normals, self.rigidity/2**iteration)

        bpy.ops.object.mode_set(mode=recall_mode)
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(Planarize.bl_idname, text="Planarize")


def register():
    bpy.utils.register_class(Planarize)
    bpy.types.VIEW3D_MT_edit_mesh.append(menu_func)


def unregister():
    bpy.utils.unregister_class(Planarize)
    bpy.types.VIEW3D_MT_edit_mesh.remove(menu_func)


if __name__ == "__main__":
    register()
