"""print_spaghetti -- author 3D-printer toolpaths directly from mesh data.

Blender 5.0+ extension (see ``blender_manifest.toml``; no legacy ``bl_info``).
Submodules use relative imports per Blender's extension policy.

This cut implements: read *literal* objects (verts + edges + Skin radius),
flatten to a print-order move list, export G-code, and animate an Empty walking
that same move list. Extruding strokes (edges) become ``G1 + E`` moves; guide
vertices (lone verts / gaps in the index timeline) become ``G0`` travels.
Materialize, collide, and the fix tools are deferred.
"""

from . import props
from . import animate
from . import ui


def register():
    props.register()
    animate.register()
    ui.register()


def unregister():
    ui.unregister()
    animate.unregister()
    props.unregister()
