# print_spaghetti - core design

Only what cannot be guessed; the options at the end plug in unchanged.

- Vertex index is the print-order timeline within an object, for strokes and
  travels alike (not a topological walk) - which is what makes select-prev/next
  and every fix tool well-defined.
- Object name in natural sort is the only invented ordering convention;
  everything else is read from native mesh data.
- The Skin modifier's per-vertex radius is the bead cross-section (width 2rx,
  height 2ry, read from the base mesh) and its root flag is the seam - bead
  shaping and start point are authored entirely with existing Skin tools.
- An object is a literal (verts+edges, prints as-is) or a recipe (has faces);
  literals materialize to an identical copy, so Materialize touches only recipes,
  is idempotent, and each `.path` supersedes its whole source.
- One generator feeds materialize, gcode, animate, and collide off a single
  flattened move list, so no two can disagree on where the head is.
- Collision reports the first hit only, order-aware against beads laid before
  that move, and drops you into edit mode selected on the crash - stateless, no
  hit list, re-run after each fix.
- Insert/Subdivide acts on gaps, not vertices, under rule G: cut the gap between
  any two adjacent selected verts, and for a selected vert with no selected
  neighbor cut the gap to its successor - no fallback, so an isolated last vertex
  does nothing.
- Deletion is left to the built-ins (it compacts, preserving order); only
  insertion manages index, and reordering is pairwise Separate/Join with the
  target object active.
- Deliberately absent: any sidecar path format, physics/rigid-body collision, and
  a collision hit list; the volume slicer is the sole non-native piece and is
  deferred.

## Options

1. **Volume fill**: planar-Z slicing or surface-following non-planar fill.
   Planar reuses standard slicer logic off the shelf; non-planar matches the
   literal-Z ethos of the rest but has no ready-made algorithm.
2. **Material slot meaning**: extruder/tool change or speed+temperature preset.
   Tool change enables true multi-material; preset reuses one nozzle for regime
   switches with no hardware.
3. **Face fill pattern**: rectilinear or concentric. Rectilinear is simplest and
   fastest to generate; concentric follows the perimeter and needs no seam
   between fill and wall.
