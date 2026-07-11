# G-code by Hand — Notes

A working set of notes on generating 3D-printer G-code directly (without a slicer),
based on a PrusaSlicer-exported "letter o" and targeting a stock Creality Ender 3.

---

## 1. Reading the file: structure, coordinate modes, and the extrusion math

Stripped of comments, the file is three blocks: a printer-specific startup, a list of
`G1` moves that *is* the letter, and a teardown — plus a config dump at the end that the
printer completely ignores (everything after a `;` is a comment). Here's what actually
matters to emit that middle block yourself.

### The coordinate modes are the thing to internalize first

Near the top the file sets `G90` (absolute XYZ) and `M83` (*relative* extrusion). That
combination is the key to reading every move line:

```gcode
G1 X102.168 Y92.803 E.01273
```

The X/Y are an absolute destination — "go to this point." But the E is *not* a position;
in `M83` mode it's "push this many mm of filament *during this move*." So E is a
per-segment delta, which is convenient because it decouples from history — you never
accumulate a running total. (If you ever switch to `M82` absolute extrusion, E becomes
cumulative and you'll be adding up forever. Relative is much easier to generate.)

### Computing E is the only genuinely non-trivial part

The slicer figured out how much plastic each segment needs; your generator has to do the
same. The formula is just "volume of the bead = volume of filament consumed":

```
E = (cross_section_area × segment_length) / (π × filament_radius²)
```

The subtlety is the cross-section. A naive `width × height` rectangle overshoots.
PrusaSlicer models the bead as a rounded rectangle (a *stadium*: a rectangle with
semicircular caps). Checked against the file's first extruding move — segment length
0.579 mm, width 0.307 mm, layer height 0.2 mm, 1.75 mm filament:

- rectangle model → E = 0.01480
- stadium model → E = **0.01273** ← matches the file exactly

So the model to use is:

```
area = (width − height) × height + π × (height / 2)²
```

Get this right and prints won't under- or over-extrude.

### Everything is modal (sticky)

`G1 F1200` appears once, then a run of moves with no F — the feedrate persists until
changed. Same for position: a move only lists the axes that change. So your generator
carries state and emits only what differs. `F` is **mm/min**, not mm/s.

### Layers and retraction are quality, not correctness

The letter is three layers (Z .2, .4, .6). At each layer change the file retracts
(`G1 E-5`), lifts Z, travels, un-retracts (`G1 E5`), then prints — and ends each
perimeter with a small negative-E "wipe." None of that is mandatory to get *a* print;
it's what stops stringing and blobs. For a first experiment you can skip retraction
entirely, accept some stringing, and add it back once the geometry works.

### What to care about, concretely

- **Copy the startup and teardown verbatim** from a working slice for *your* printer —
  homing (`G28`), heating with the blocking waits (`M109`/`M190`), the prime line, and
  the cooldown. Don't reinvent these; the temperature waits are a safety/clog issue.
- **Generate the middle yourself**: a sequence of `G1 X Y E` moves at a fixed Z per
  layer, with E from the formula above, F set once.
- **Mind the modal state** so you emit minimal, consistent lines.
- **Drop all the trailing junk** — `; prusaslicer_config`, `; objects_info`, the filament
  stats. The printer never reads it. (`objects_info` only matters if you use Prusa's
  cancel-individual-object feature.)

---

## 2. Every command in the file, the feed rate, and acceleration vs width

17 distinct commands. Quick mental model: **G-codes are motion/geometry** (standardized
across machines), **M-codes are "machine" miscellany** (heaters, fans, motors — more
firmware-specific).

### Motion and positioning

- **G28** (1×) — home all axes; the printer finds its physical zero.
- **G1** (213×) — controlled (extruding or travel) move. The workhorse — it's the entire letter.
- **G92** (5×) — set the current position without moving. Always `G92 E0` here: "call the
  extruder's current position zero." Bookkeeping reset.
- **G4** (1×) — dwell/pause. `G4 S30` waits 30 seconds (lets the nozzle partially warm).
- **G21** (1×) — units = millimeters. (`G20` would be inches; you'll basically never see it.)
- **G90** (2×) — absolute coordinates for X/Y/Z.
- **M83** (2×) — relative mode for the extruder (E is a per-move delta).

### Temperature

- **M104** (4×) — set nozzle temp and *move on immediately* (no waiting).
- **M109** (1×) — set nozzle temp and *block until it's reached*.
- **M140** (2×) — set bed temp, no wait.
- **M190** (1×) — set bed temp, wait until reached.

The pattern: `M104`/`M140` start the heaters early so things warm in parallel;
`M109`/`M190` are the gate right before printing that guarantees you're at temperature.
Forgetting the waiting variants is a classic way to clog a nozzle (cold extrusion).

### Fan and motors

- **M107** (3×) — fan off. (`M106 S255` would turn it on; the part prints fast enough
  cold that the part-cooling fan stays off.)
- **M84** (1×) — disable stepper motors at the end.

### Machine motion limits

- **M201** — max acceleration per axis.
- **M203** — max feedrate per axis.
- **M204** — print/travel acceleration. `S500 T1000` = S is printing accel, T is travel
  accel (the comment says "retract" but on current Marlin/Prusa firmware T is travel).
- **M205** — jerk limits (how abruptly speed can change at direction changes).

### What's the feed rate?

There isn't *a* feed rate — `F` is modal and context-dependent, set per situation and
remembered until changed. Units trip people up: **F is mm/min**, so divide by 60 for
mm/s. The values in the file:

| F value | mm/s | Used for |
|---|---|---|
| F9000 | 150 | travel moves & Z hops (fast, non-extruding) |
| F7200 | 120 | fast travel |
| F5000 | 83 | travel during priming |
| F3600 | 60 | retraction (pulling filament back) |
| F3000 | 50 | initial positioning |
| F2400 | 40 | un-retraction (pushing it back) |
| F1500 | 25 | printing perimeters on layers 2–3 |
| F1200 | 20 | printing perimeters on the first layer |
| F600 | 10 | the careful Z lifts at the end |
| F240 | 4 | slow initial Z moves |

So the print speed that actually lays plastic is 20 mm/s (first layer) to 25 mm/s (above)
— deliberately slow because it's a tiny part. Travel is 150 mm/s. When generating your
own, emit `G1 F...` once whenever you change regime (travel vs print) and let it ride.

### Acceleration/deceleration vs extrusion width — do you have to care?

Short answer: **care about width, don't worry about acceleration.**

Because E is expressed as *distance*, not time, the firmware synchronizes X/Y/E so they
start and stop together — when the head slows into a corner, the extruder slows by the
same proportion. So the amount of plastic per millimeter stays constant no matter how the
head accelerates. That's the whole reason E-as-distance is nice: extrusion is locked to
geometry, and acceleration is the firmware's problem, not yours. You can omit
`M201/M204/M205` entirely and the printer falls back to its stored defaults; prints still
come out. Those lines are just the slicer overriding machine motion settings — safe to
inherit as boilerplate or drop.

**Width is the one you must own**, because width (with layer height) feeds the E formula.
Good news: you don't need the per-segment width wobble in the file (0.307, 0.311, 0.312…).
That variation is PrusaSlicer micro-adjusting to fit corners and thin features; it's an
optimization, not a requirement. Pick one sensible width — roughly 1.0–1.2× nozzle
diameter, so ~0.4–0.48 mm for a 0.4 mm nozzle — use it everywhere, and the E math stays
simple.

Where the two *do* physically interact: at high acceleration the molten plastic's
pressure lags the commanded flow, so you get faint under-extrusion when speeding up and a
little blob when slowing into a corner. The fix is "pressure advance" / "linear advance"
(`M900`), and it's a tuning refinement — not something you need for a clean-enough first
result. So for the "diagonal bars and crazy stuff" stage: fixed width, modest print
speed, ignore acceleration, revisit pressure advance only if corners bother you.

---

## 3. Segmentizing a move — should you expect pauses between commands? (Ender 3)

Two layers: by design there's no pause, but on a stock Ender 3 there's a regime where
pauses absolutely appear.

### By design: no

Marlin (what the Ender 3 runs) doesn't execute moves one-at-a-time with a stop between
them. It has a *look-ahead planner* with a buffer of queued moves (16 by default). It
looks ahead across the queued segments and computes a "junction speed" at each boundary
based on how sharply the direction changes. For collinear segments — a diagonal bar cut
into 100 pieces — the junction speed is just full speed, so the head sails straight
through as if it were one move. Motion-wise, a straight line split into 100 collinear
`G1`s is identical to one `G1`. That's the entire purpose of look-ahead: to *not* stop at
every comma.

### In practice on a stock Ender 3: yes, past a threshold

The original Ender 3 board is an 8-bit AVR (ATmega1284P at 16 MHz on Creality's 1.1.x /
Melzi board). Parsing each line and running the planner costs compute, and that little
chip can only do it so fast. If segments execute *faster* than the MCU can plan the next
ones, the buffer drains. An empty buffer means the printer has nothing planned to execute,
so it **must stop and wait** — refill, move, drain, stop, repeat. That's planner
starvation, and it shows up as rhythmic micro-stutter (often audible, like a coffee-grinder
click) plus surface artifacts and an effective speed drop. This is the well-known failure
mode for high-segment-count models on 8-bit Creality boards.

### The real variable

Not "segment count" by itself, but **how long each segment takes to execute versus how
long it takes to plan.** Rule of thumb: keep per-segment execution time above ~1 ms,
comfortably a few ms. Execution time = segment_length ÷ feedrate. At a lettering speed of
20 mm/s (0.02 mm/ms), even a 0.1 mm segment takes 5 ms, and a 0.5 mm segment takes 25 ms —
nowhere near the danger zone. Trouble starts with *tiny segments at high speed*: at
100 mm/s a 0.1 mm segment is 1 ms, where an 8-bit board starts choking. (Enabling Linear
Advance makes planning heavier, lowering the ceiling further.)

### Practical notes

- For slow, deliberate paths like letters and diagonal bars, segmentize as finely as you
  want — you won't see pauses.
- Print from **SD card, not USB**. Streaming over serial (OctoPrint, Pronterface) adds a
  *second* bottleneck — host latency and serial throughput can create gaps between
  commands independent of the planner. SD removes that variable.
- Even with no starvation, every segment boundary that *changes direction* incurs a real
  slowdown to its junction speed. Finely faceting a **curve** isn't a "pause," but it makes
  the head constantly decelerate-accelerate through each micro-corner, dropping average
  speed and feeding the flow-lag artifacts above. Faceting a **straight** line costs
  nothing.
- Caveat on "Ender 3": an Ender 3 V2 or newer likely has a 32-bit STM32 board (Creality
  4.2.2-style) that handles dense segmentation far more gracefully. And flashing **Klipper**
  moves planning to the host Pi entirely — the printer just executes pre-computed steps and
  starvation basically stops being a concern. The original 8-bit board is the one that's
  genuinely "stupid" here.

If you want curves without flooding the board with `G1` lines, Marlin's arc commands
`G2`/`G3` let you send one line for a whole arc; the firmware re-segments it internally.
Over USB that's a real win (far fewer lines to stream); from SD the benefit is smaller
since the chip still computes the segments.
