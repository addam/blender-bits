"""flatten_moves: per-object vertex sequences -> one print-order move list.

The single move list every downstream sink reads (export now; animate/collide
later), so they can never disagree about where the head is (design *Pipeline*).

A move is a plain dict:

    {"pos": Vector world-space, "extruding": bool, "w": width, "h": height}

``extruding`` describes the segment *into* this point from the previous move.
The very first move of the whole list, and the first move of every object, is a
travel (extruding=False) -- the auto-inserted hop between ops (design
*G-code export*). Widths carry through for the E math; on a travel they are
unused.
"""


def flatten_moves(sequences):
    """Concatenate ordered object sequences into a flat move list.

    ``sequences`` is the ``[(name, [records])]`` from ``generate.read_objects``,
    already in natural-name order.
    """
    moves = []
    for _name, seq in sequences:
        for i, rec in enumerate(seq):
            # First record of each object forces a travel to its start; within
            # an object, extrude_in decides (edge -> extrude, gap -> travel).
            extruding = rec["extrude_in"] if i > 0 else False
            moves.append({
                "pos": rec["pos"],
                "extruding": extruding,
                "w": rec["w"],
                "h": rec["h"],
            })
    return moves


def sample_path(moves, speed, fps, frame_start):
    """Arc-length keyframe times for the flattened move list (design *Animate*).

    Returns ``[(frame, pos_world, extruding)]`` -- one sample per move endpoint.
    ``frame = frame_start + round(cum_mm / speed * fps)``: constant speed, so
    per-move feedrates are ignored and travels move at the same rate as strokes.
    With LINEAR interpolation between these arc-length-spaced frames, velocity is
    constant everywhere. Shared by Animate and (later) Collide so they agree.

    ``speed`` is mm/s, ``fps`` frames/s; positions are already world-space.
    """
    samples = []
    cum_mm = 0.0
    prev = None
    for mv in moves:
        p = mv["pos"]
        if prev is not None:
            cum_mm += (p - prev).length
        if speed > 0.0:
            frame = frame_start + round(cum_mm / speed * fps)
        else:
            frame = frame_start
        samples.append((frame, p, mv["extruding"]))
        prev = p
    return samples
