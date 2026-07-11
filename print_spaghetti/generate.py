"""Reader: mesh objects -> ordered per-object vertex sequences.

This is the minimum of design.md's ``objects_to_strokes``: it handles only
*literals* (verts + edges, no faces) and derives, per object, one flat sequence
of vertex records in the universal ordering rule -- **vertex index is the
timeline**. Recipes (faces / tubes / solids) are deferred and skipped with a
warning.

Each record is a plain dict so downstream modules stay dependency-light:

    {"pos": Vector world-space, "w": bead width mm, "h": bead height mm,
     "extrude_in": bool}   # extrude_in: does the move from the previous record
                           # in this sequence lay material?

``extrude_in`` is True when an edge connects a record to its index-predecessor,
False otherwise (a break -> travel). A lone vertex (in no edge) therefore always
becomes a travel waypoint, which is exactly the "guide vertex" case. The first
record of a sequence has extrude_in=False (you travel to a path's start).
"""

import re

import bmesh
import mathutils


def natural_key(name):
    """Sort key splitting digit runs so '020_walls' < '100_infill' numerically."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", name)]


def target_objects(context):
    """Selected mesh objects, or all scene meshes when nothing is selected."""
    selected = [o for o in context.selected_objects if o.type == "MESH"]
    if selected:
        return selected
    return [o for o in context.scene.objects if o.type == "MESH"]


def object_scale(obj):
    """Mean of the world-matrix scale; Skin radius is in local units."""
    sx, sy, sz = obj.matrix_world.to_scale()
    return (abs(sx) + abs(sy) + abs(sz)) / 3.0


def object_to_sequence(obj, settings):
    """Return the ordered vertex-record list for one literal mesh object.

    Returns None (and leaves it to the caller to warn) if the object is a
    recipe -- i.e. carries any face.
    """
    mesh = obj.data
    if len(mesh.polygons) > 0:
        return None  # recipe; deferred (design *Open / deferred*)

    scale = object_scale(obj)
    matrix = obj.matrix_world

    bm = bmesh.new()
    bm.from_mesh(mesh)  # BASE mesh, never evaluated_get (design *Bead width*)
    try:
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        skin = bm.verts.layers.skin.active  # may be None -> use fallbacks

        # Adjacency by vertex index: is there an edge between i and its
        # index-predecessor? (Convention: indices increase along a stroke.)
        edge_pairs = set()
        for e in bm.edges:
            a, b = e.verts[0].index, e.verts[1].index
            edge_pairs.add((min(a, b), max(a, b)))

        verts = sorted(bm.verts, key=lambda v: v.index)
        seq = []
        prev_index = None
        for v in verts:
            if skin is not None:
                rx, ry = v[skin].radius
                w = 2.0 * rx * scale
                h = 2.0 * ry * scale
                # A zero radius means "unshaped" -> fall back to globals.
                if w <= 0.0:
                    w = settings.line_width
                if h <= 0.0:
                    h = settings.layer_height
            else:
                w = settings.line_width
                h = settings.layer_height

            extrude_in = (prev_index is not None
                          and (prev_index, v.index) in edge_pairs)
            seq.append({
                "pos": matrix @ v.co.copy(),
                "w": w,
                "h": h,
                "extrude_in": extrude_in,
            })
            prev_index = v.index
        return seq
    finally:
        bm.free()


def read_objects(objects, settings):
    """Classify + order a list of objects.

    Returns ``(sequences, skipped)`` where ``sequences`` is a list of
    ``(name, [records])`` sorted by natural object name, and ``skipped`` is the
    list of names dropped because they are recipes (have faces).
    """
    meshes = [o for o in objects if o.type == "MESH"]
    meshes.sort(key=lambda o: natural_key(o.name))

    sequences = []
    skipped = []
    for obj in meshes:
        seq = object_to_sequence(obj, settings)
        if seq is None:
            skipped.append(obj.name)
        elif seq:
            sequences.append((obj.name, seq))
    return sequences, skipped
