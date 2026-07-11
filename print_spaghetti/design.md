# print_spaghetti -- design spec

A Blender extension for authoring 3D-printer toolpaths directly from mesh data,
with no slicer in the loop. You model the paths you want; Blender's native data
carries almost all the information, so the format we invent is close to nothing.

Companion doc `gcode-notes.md` covers the machine-level G-code detail (Ender 3 /
Marlin, `G90`+`M83`, feedrates, retraction, the stadium extrusion model). This
doc is the Blender-side design. Target: Blender 5.1 extension (`blender_manifest.toml`).

## Core principle

Geometry is literal: a vertex's world position (`object.matrix_world @ co`) is a
nozzle position, Z included, so paths are naturally non-planar. Topology
classifies what kind of move each element is. Object names and vertex indices
decide order. Nothing lives in a sidecar format.

## Element mapping

| Blender element | Detected as | Operation |
|---|---|---|
| Lone vertex (in no edge) | isolated vert | Travel (G0) to that point; a run of them = travel waypoints in index order |
| Wire polyline (edges bordering no face) | connected wire component | Extruding stroke (G1 + E) along the chain |
| Face | polygon | Filled region at the face plane, bead spacing = line width |
| Tube surface (open quad grid, two boundary loops, consistent ring counts) | cylinder | Spiralized: ramp Z around each ring into one seamless helix |
| Closed manifold mesh (every edge borders 2 faces) | volume | Sliced solid: perimeters + infill along Z |

"Spiral if possible" falls back to per-ring contours when the tube is not a
clean genus-0 grid.

## Ordering

Global print order between objects: natural-sort by object name. Convention is a
numeric prefix (`010_skirt`, `020_walls`, `030_infill`). This is the only naming
convention the user must learn.

Within an object, order is universal and uniform:

- **Vertex index = the timeline.** A stroke is a run of connected verts with
  indices increasing along it; a travel is a run of lone verts ordered by index.
  One rule for everything, which is what makes "select prev/next" and the fix
  tools well-defined.
- **Root vertex = seam / start.** The Skin modifier's root flag (`use_root`) is
  persistent, drawn distinctly, and marks where an object's path begins. Active
  vertex is the fallback when no root is marked.

## Bead width via the Skin modifier

The Skin modifier's per-vertex radius layer *is* the bead cross-section, and the
tube it renders is a live preview of the deposited material -- WYSIWYG width, no
invented data channel.

- `width  = 2 * rx * object_scale`, `height = 2 * ry * object_scale`, where
  `(rx, ry)` is the vertex's skin radius. The two half-extents map to bead width
  and local layer height; elliptical radii give tapered/varying beads.
- Read the **base mesh** skin layer (`bm.verts.layers.skin`), never
  `evaluated_get()` -- otherwise Subdivision or other modifiers corrupt widths.
  Apply object scale, since skin radius is in local units.
- Authoring uses only native tools: Ctrl+A (Skin Resize) to shape beads,
  Skin > Mark Root for the seam, Equalize Radii / Symmetrize for uniform or
  mirrored paths.
- Faces are not skinned; fill bead width comes from the global/param value, and
  the region's perimeter is what you visualize as skinned edges.
- Global nozzle-width setting is only a fallback for meshes with no skin layer.

## Literal vs recipe

Every object is exactly one of two legible kinds:

- **Literal**: verts + edges (skinned). Already its own preview and its own IR;
  prints as-is. Never materialized. Single source of truth.
- **Recipe**: has faces / is a tube / is a solid. A computed path, generated at
  export or reified on demand.

The gate is one line in the reader: `is_recipe = len(mesh.polygons) > 0` (plus
tube detection). Literals short-circuit to the sinks; recipes are the only thing
the materializer ever writes.

## Pipeline: one generator, four sinks

```
generate_paths(objects) -> [Stroke]        # classify + derive fills/spirals/slices
    |    Stroke = polyline + per-vertex (w,h) + root + tool/speed
    |
    +-- strokes_to_objects(strokes)         # MATERIALIZE (inverse writer)
    |
    +-- flatten_moves(strokes) -> [(p_world, extruding)]   # print-order move list
             +-- moves_to_gcode                            # EXPORT
             +-- sample_path(moves, speed) -> [(frame, p_world, extruding)]
                      +-- animate keyframes                # ANIMATE
                      +-- BVH overlap                      # COLLIDE
```

`flatten_moves` is where name order, index order, root seam, and auto-inserted
travels between ops are resolved once. Every downstream consumer reads it, so
export, animation, and collision can never disagree about where the head is.

The backbone property: `strokes_to_objects` and the reader inside
`generate_paths` are inverses, so materialize-then-export equals export-directly,
byte for byte.

## Materialize (optional first step)

Reify computed paths into editable geometry using the same schema as hand-drawn
input (wire polylines + skin radii + root). A fill becomes many short parallel
polylines (or concentric loops); a spiral becomes one helix; slices become
contours. You then edit them with the same Skin tools.

- A literal materializes to an identical copy (round-trip identity), so the
  operator **only touches recipes** and skips literals. It is idempotent and
  produces no growing pile of duplicates.
- Generated object is named off its source (`030_infill` -> `030_infill.path`),
  placed in a `Toolpaths` collection, and stamped with a custom property
  `path_source = "030_infill"`.
- Export resolution: for each source, if a live object references it, use that;
  otherwise generate on the fly. A `.path` supersedes its whole source, so you
  can materialize some regions, leave others, and never double-print.
- Re-materializing deletes prior `.path` objects for those sources first.
- Recommended habit (rewarded by the name ordering): one role per object.

## G-code export

See `gcode-notes.md` for the machine detail. Key points the generator owns:

- `G90` absolute XYZ, `M83` relative E (per-segment delta, no running total).
- Z comes from geometry; layer height enters only as bead cross-section.
- Extrusion volume uses the **stadium** cross-section (matches PrusaSlicer):
  `area = (width - height) * height + pi * (height/2)^2`, then
  `E = area * seg_len / (pi * (filament_d/2)^2)`.
- Tapered beads (width/height varying per vertex) integrate in closed form over
  a segment; non-tapered collapses to `area * seg_len`.
- Modal output: emit `F` and only the axes that change; carry state.
- Travel between ops = retract + G0 at travel speed + unretract, auto-inserted
  unless explicit lone-vert waypoints specify the path (collision avoidance).
- Start/end G-code from named Text datablocks (copied verbatim per printer).
- Material slot -> tool/extruder or a speed+temperature preset (multi-material).

## Parameters (where they live, natively)

- Scene PropertyGroup: filament diameter, nozzle/line width, default layer
  height, print/travel speed, temps, start/end Text datablock refs.
- Object custom properties: per-object overrides (speed, flow, width, layer_height).
- Skin radius: per-vertex width/height (authoritative when present).
- Material slot: tool/extruder or preset.

## Animate

An Empty walks the flattened path at one reasonable constant speed (motion
preview, not a time-accurate sim, so per-move feedrates are ignored).

- Arc-length keyframing: `frame = frame_start + round(cum_mm / speed * fps)`.
- Location fcurves set to **LINEAR** interpolation -- with arc-length-spaced
  frames this makes velocity constant everywhere, travels included. (Default
  Bezier would ease at every vertex and break constant speed.)
- Locations are world-space (baked `matrix_world`), so one Empty covers all
  objects. Set scene `frame_end` to the last computed frame.
- Optional: keyframe an `extruding` custom prop (0/1, CONSTANT interp) to drive
  color/size for pen-up vs pen-down.

## Collide

`mathutils.bvhtree.BVHTree.overlap()`, not the rigid-body system (which is
sim-based, imprecise, and order-unaware). Reads the same `sample_path` list as
Animate, so they agree by construction.

- **First hit only**, early-exit. This is what makes it cheap enough to re-run in
  a loop; after fixing the first collision you may create another, so you re-run
  anyway. No hit list, no scene state.
- Order-aware obstacle set = the beads deposited strictly *before* the current
  move (the same evaluated Skin tubes the user previews), plus an optional
  collection of tagged fixtures.
- **Exclude the current bead tail** (last segment or two), or the head always
  "collides" with the line it is laying.
- Sample each move at <= smallest head feature so a thin obstacle cannot tunnel.
- Head is a low-poly envelope mesh (nozzle + heater block + fan/carriage sweep).
- On a hit: enter edit mode on the culprit, select the offending verts, set
  active vertex, snap 3D cursor to the collision point, frame it, and set the
  current frame to the collision frame (so the animation, if present, is parked
  at the crash). Stateless operator.
- Performance: head BVH is tiny (rebuild per sample); rebuild the growing printed
  BVH only per layer / every N moves.
- Collisions in a recipe have no editable elements: the fix offers to materialize
  it first, then selects into the `.path`.

## Fix tools (fix.py)

Editing the path is editing the vertex-index timeline, so these are a small
sequence editor disguised as mesh ops. Built-ins fail because they cannot insert
at a chosen index (Subdivide appends at max+1) and cannot cut between lone verts.

### Insert / Subdivide (gap model, rule G)

The operator acts on **gaps** (the interval between a vertex and its
index-successor), not on vertices, which removes the single-vertex ambiguity: one
selected vertex means one implied gap, and the new point lands at its midpoint
(midway to the next vertex).

Rule **G** picks which gaps to cut:
> Subdivide the gap between any two adjacent selected verts; and for any selected
> vertex with no selected neighbor, subdivide the gap to its successor.

No fallback: an isolated last vertex (no successor) does nothing. Rule G keys off
a local predicate, never off selection count.

- Single vert -> midway to next (the requirement).
- One edge / two adjacent verts -> just that gap (classic edge subdivide, no bleed).
- Whole stroke -> classic subdivide-all.
- Scattered single picks -> each gets its own trailing gap.

How each gap is cut is uniform: an edge across the gap -> split the edge (stays a
stroke); no edge -> insert a lone waypoint (stays a travel). Insert N verts evenly
in position, **splice indices via `bm.verts.sort()`** so they land in order, and
**interpolate the skin radius** across them (built-in Subdivide leaves skin at
default and bulges).

### Select prev / next element

Steps the active selection along the index timeline (Prev = lower index, Next =
higher), option to constrain to the current connected component, shift to
extend-select. This is how you grab the offending gap after Collide drops you on a
crash, and how you inspect what happens just before/after it.

### Delete waypoint (optional convenience)

Context-aware: plain delete for a lone travel vert (neighbors reconnect straight
through), Dissolve for a degree-2 stroke vert (keep bead continuity; plain delete
would sever the stroke and insert a travel), delete-plus-remark-root for an
endpoint. Built-in Ctrl+X already gives the ordering-correct result; this just
picks the verb for you.

## Reorder within an object

Separate + Join, used pairwise:

- Separate (P > Selection) is order-preserving on both pieces.
- Join concatenates **active object first**, other appended after. Choosing the
  active object gives either concatenation order.
- Join only two at a time: with 3+, the order among non-active objects is
  internal (creation order, not name order) and must not be relied on.

This reorders the intra-object index timeline; cross-object order stays governed
by name, so the two layers do not overlap.

## Module layout

```
print_spaghetti/
  blender_manifest.toml
  __init__.py       register panel + operators + scene props
  props.py          PrinterSettings PropertyGroup
  generate.py       objects_to_strokes (reader, literal/recipe gate) + fill/spiral/slice
  flatten.py        flatten_moves + sample_path
  materialize.py    strokes_to_objects (inverse writer: wire mesh + skin layer + root)
  gcode.py          moves_to_gcode
  animate.py        Empty keyframing
  collide.py        first-hit BVH check + hand-off
  fix.py            gap-model Subdivide, select prev/next, delete
  ui.py             N-panel buttons; edit-mode pie/context menu for fix tools
```

## Verified Blender 5.1 behavior (empirical)

Facts the ordering model depends on, tested in background mode with
index-tagged vertices:

- **Vertex deletion compacts, no swap-remove.** Removing index 2 of 0..5 yields
  `[0,1,3,4,5]` renumbered contiguously; the max index stays at the end. Relative
  order is preserved (bmesh pool allocator skips the freed slot rather than
  backfilling from the tail). So deletion needs no special handling; only
  insertion must manage index via `bm.verts.sort()`.
- **Separate is order-preserving** on both the remaining mesh and the new piece.
- **Join = active first, others appended.** A-active gives `[A,B]`, B-active
  gives `[B,A]` -- both orders reachable. With 3+ objects the non-active order
  follows internal (creation) order, not name; so reorder pairwise.
- Join bakes each object's transform into the active object's local space; world
  positions (what paths resolve through) are unchanged.

## Open / deferred

- Volume slicer (closed manifold -> perimeters + infill) is the one non-native
  piece; stub it to the `Stroke` interface and build the vert/edge/face/spiral
  paths first.
- "Reroute around obstacle silhouette" fix is advanced; stub to the same
  index-splice core as Subdivide.
