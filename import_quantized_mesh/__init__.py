import bpy
import struct
import math
import gzip
import os

from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

EARTH_RADIUS = 1e5 # 6371e3
MAX_QUANT = 32767.0

def maybe_decompress(data):
    return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data

def zigzag_decode(v):
    return (v >> 1) ^ (-(v & 1))

def hwm_decode(codes):
    result = []
    highest = 0
    for code in codes:
        result.append(highest - code)
        if code == 0:
            highest += 1
    return result

def parse_header(data):
    vals = struct.unpack_from('<3d2f4d3d', data, 0)
    min_h = float(vals[3])
    max_h = float(vals[4])
    return min_h, max_h, 88

def parse_vertices(data, offset):
    vertex_count = struct.unpack_from('<I', data, offset)[0]
    offset += 4
    if vertex_count == 0:
        return [], [], [], offset, vertex_count
    count = vertex_count
    fmt = f'<{count}H'
    needed = count * 2
    u_enc = struct.unpack_from(fmt, data, offset)
    offset += needed
    v_enc = struct.unpack_from(fmt, data, offset)
    offset += needed
    h_enc = struct.unpack_from(fmt, data, offset)
    offset += needed
    u = [0] * count
    v = [0] * count
    h = [0] * count
    du = dv = dh = 0
    for i in range(count):
        du += zigzag_decode(u_enc[i])
        dv += zigzag_decode(v_enc[i])
        dh += zigzag_decode(h_enc[i])
        u[i] = du
        v[i] = dv
        h[i] = dh
    return u, v, h, vertex_count, offset

def padding(offset, boundary):
    return (-offset) % boundary

def parse_indices(data, vertex_count, offset, multiplier=1):
    use32 = vertex_count > 65536
    boundary = 4 if use32 else 2
    offset += padding(offset, boundary)
    triangle_count = struct.unpack_from('<I', data, offset)[0]
    offset += 4
    indices_count = triangle_count * multiplier
    if indices_count == 0:
        return [], offset
    if use32:
        fmt = f'<{indices_count}I'
        bytes_needed = 4 * indices_count
    else:
        fmt = f'<{indices_count}H'
        bytes_needed = 2 * indices_count
    indices = struct.unpack_from(fmt, data, offset)
    if multiplier > 1:
        indices = hwm_decode(indices)
        print("max index:", max(indices), "vertex count:", vertex_count)
        indices = [tuple(indices[i:i+multiplier]) for i in range(0, len(indices), multiplier)]
    offset += bytes_needed
    return indices, offset

def tile_bounds_from_tms(z, x, y):
    scale = 180 * 2**-z
    return x * scale - 180, y * scale - 90, (x + 1) * scale - 180 , (y + 1) * scale - 90

def to_spherical_vertices(u_list, v_list, h_list, bounds, min_h, max_h):
    west, south, east, north = bounds
    vertices = []
    for u, v, h in zip(u_list, v_list, h_list):
        lon = (east - west) * (u / MAX_QUANT)
        lat = (north - south) * (v / MAX_QUANT)
        alt = (max_h - min_h) * (h / MAX_QUANT)
        vertices.append((EARTH_RADIUS * lon * math.cos(lat), EARTH_RADIUS * lat, alt))
    return vertices

def create_mesh_in_blender(name, vertices, edges=[], faces=[]):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj

class ImportQuantizedMesh(bpy.types.Operator, ImportHelper):
    bl_idname = "import_mesh.quantized_mesh"
    bl_label = "Import Quantized Mesh (.terrain)"
    filename_ext = ".terrain"
    filter_glob: StringProperty(
        default="*.terrain",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        filepath = self.filepath
        # Try to infer z/x/y from path: expect .../z/x/y.terrain
        parts = os.path.normpath(filepath).split(os.sep)
        try:
            z = int(parts[-3])
            x = int(parts[-2])
            y = int(os.path.splitext(parts[-1])[0])
        except Exception:
            self.report({'ERROR'}, "Input path must look like .../z/x/y.terrain")
            return {'CANCELLED'}
        with open(filepath, 'rb') as f:
            raw = f.read()
        data = maybe_decompress(raw)
        min_h, max_h, offset = parse_header(data)
        u_list, v_list, h_list, vertex_count, offset = parse_vertices(data, offset)
        bounds = tile_bounds_from_tms(z, x, y)
        vertices = to_spherical_vertices(u_list, v_list, h_list, bounds, min_h, max_h)
        faces, offset = parse_indices(data, vertex_count, offset, 3)
        print("bounds:", bounds, min_h, max_h)
        create_mesh_in_blender(f"QuantizedMesh_{z}_{x}_{y}", vertices, faces=faces)

        for name in ["west", "south", "east", "north"]:
            boundary, offset = parse_indices(data, vertex_count, offset, 1)
            boundary = list(zip(boundary, boundary[1:]))
            print(boundary)
            create_mesh_in_blender(f"Boundary_{z}_{x}_{y}_{name}", vertices, edges=boundary)

        self.report({'INFO'}, f"Imported {filepath} as Quantized Mesh")
        return {'FINISHED'}


def menu_func_import_quantized_mesh(self, context):
    self.layout.operator(ImportQuantizedMesh.bl_idname, text="Cesium Quantized Mesh (.terrain)")


def register():
    bpy.utils.register_class(ImportQuantizedMesh)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_quantized_mesh)


def unregister():
    bpy.utils.unregister_class(ImportQuantizedMesh)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_quantized_mesh)


if __name__ == "__main__":
    register()
