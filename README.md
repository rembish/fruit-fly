# fruit-fly 🪰

[![checks](https://github.com/rembish/fruit-fly/actions/workflows/checks.yml/badge.svg)](https://github.com/rembish/fruit-fly/actions/workflows/checks.yml)

A fly that lives on your desktop — Linux, macOS or Windows — driven by the
**complete real brain of a fruit fly**: the [FlyWire](https://flywire.ai/)
connectome of adult *Drosophila melanogaster*, 139,255 neurons and ~34
million synapses, every one of them mapped from an actual fly by actual
scientists, simulated live as leaky integrate-and-fire neurons while the
sprite buzzes over your windows.

No scripted behavior, no random walk. When the fly dodges your cursor it is
because your cursor was fed into its real looming-detector neurons (LC4,
LPLC2), which drove its real giant fiber escape neuron (DNp01) through real
synapses, exactly the circuit a living fly uses to evade your rolled-up
newspaper. When it takes off, lands, or jinks for no reason at all — a
neuron decided to.

![A fruit fly walking and flying across a desktop, over this README, while a
terminal beside it logs the neurons firing behind each move](https://raw.githubusercontent.com/rembish/fruit-fly/master/docs/demo.gif)

On the right, the fly crosses its own README. On the left, its log: every
jink, saccade and `ESCAPE!` in that recording is a real neuron reaching
threshold, printed as it happens.

## How it works

```
your screen ──► RETINOTOPIC EYES: 785+796 real eye columns, 6,670 mapped
                photoreceptors + 4,541 lamina cells, each driven by the
                actual pixels its column sees (cursor rendered with
                perspective: it looms as it approaches)               ─┐
                                                                       ▼
                     WHOLE-BRAIN LIF SIMULATION (139,255 neurons,
                     2.7M connections, ~34M synapses, real time)
                                                   │
                     giant fiber DNp01 ── escape! ─┤
                     DNa02 L/R rate difference ── steering
                     descending pool (1,305) ── fly / land / saccade
                                                   ▼
                     a small transparent window that follows the fly
```

The eyes are real: each eye's hexagonal lattice of columns comes from the
FlyWire column assignments (Matsliah et al. 2024), R1-6 photoreceptors are
assigned to columns through their actual lamina partners, and an expanding
dark disc on the retina drives the loom detectors and giant fiber through
nothing but anatomy (`tests/test_retina.py` proves it: LC4 ramps with
expansion, lateralized to the stimulated eye, weak response to full-field
dimming). The emergent loom signal is weaker than a real fly's, so by
default a scaled-down direct LC4/LPLC2 injection backs it up for reliable
cursor dodging — run with `--pure-retina` to trust the eyes alone.

The model follows [Shiu et al. 2024, *Nature*](https://pubmed.ncbi.nlm.nih.gov/37205514/)
(the first whole-brain fly simulation): connection weight = synapse count,
sign from the machine-predicted neurotransmitter, uniform LIF parameters
from fly electrophysiology. Connectivity comes straight from the public
[FlyWire Codex](https://codex.flywire.ai/) data dump (snapshot 783,
downloaded on first run, ~50 MB).

## Install & run

The brain, senses, motor and the cairo-drawn sprite are shared; only the
window layer is per-platform, in `fruitfly/ui/` (see [`ui/base.py`](https://github.com/rembish/fruit-fly/blob/master/fruitfly/ui/base.py)
for the interface a backend implements).

| platform | backend | needs |
|---|---|---|
| Linux (X11, or Wayland via XWayland) | `gtk` | GTK3 + PyGObject, a compositing WM |
| macOS 10.15+ | `cocoa` | PyObjC, Screen Recording permission for vision |
| Windows 10/11 | `win32` | nothing extra (pure `ctypes`) |

All three run on real hardware. Linux is the one developed against day to
day; on macOS and Windows the fly appears, flies, draws and quits, but the
permission-gated vision path and the click-through swatting have had little
use, so reports are welcome. WSL is *not* supported: WSLg gives X no desktop
to grab, so the fly is blind there and its window fights the Windows
foreground. The app says so at startup and points at the native build.

**Linux** (Debian/Ubuntu/Mint):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-numpy
# the first run downloads and compiles the brain (~50 MB, one time)
python3 -m fruitfly
```

Transparency needs a compositing window manager (MATE: System → Preferences
→ Windows → enable compositing); macOS and Windows always composite.

**macOS** (Homebrew). Not the `python3` from Xcode: that is 3.9, which this
project does not support, and pyobjc-core has no 3.9 wheel, so pip falls
back to a source build that fails on current clang.

```bash
brew install python@3.13 cairo pkgconf
python3.13 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz pycairo numpy
python -m fruitfly
```

First launch asks for **Screen Recording** permission — that is the fly's
eyesight, reading the pixels around itself. Decline and it still flies, just
blind. No Accessibility permission is needed: swat detection uses the
window's own hit-testing.

**Windows** (PowerShell, Python from python.org):

```powershell
pip install numpy pycairo
python -m fruitfly
```

Nothing extra and no permission prompt. The fly is a layered window, so
Windows hit-tests it per-pixel by alpha: clicks land on the fly and pass
through everywhere else. On Windows 10 2004+ it is also excluded from screen
capture so it cannot see itself, which means screen recorders cannot see it
either — pass `--recordable` to film it.

**As a package**, once the system libraries above are in place:

```bash
pip install fruitfly && fruitfly run
```

That works from a standing start on **Windows only**, where everything ships
a wheel. Everywhere else pip must build `pycairo` from source — it publishes
wheels for Windows and nowhere else, and PyGObject publishes none at all —
so a clean venv fails with "Dependency lookup for cairo with method
'pkg-config' failed" until cairo and pkg-config are installed. On Linux,
create the venv with `--system-site-packages` so it can see the distro's
PyGObject rather than trying to build one.


Options:

```
fruitfly --hud          live neural telemetry overlay (GF/DNa02/LC4 rates)
fruitfly --size 48      bigger fly
fruitfly --pure-retina  no looming injection: escapes only via the real eyes
fruitfly --no-vision    don't sample the screen into the retina
fruitfly --noise 140    more spontaneous brain activity (a more annoying fly)
fruitfly --dt 1.0       finer integration (slower; default 2.0 ms)
fruitfly --dt auto      benchmark this machine, then pick a timestep
fruitfly --recordable   let screen recorders see the fly (Windows hides it)
fruitfly --backend gtk  force a backend (gtk, cocoa, win32); default: auto
fruitfly benchmark      what timestep this machine can sustain
fruitfly calibrate      re-derive the motor thresholds for a changed brain
fruitfly test           headless 30 s behavioral test, no window
```

Only a ~150 px transparent window travels with the fly — the rest of your
screen has no window over it, and within that window only the fly's body
accepts clicks. **Clicking the fly is a swat attempt, and the fly is
mortal**:

- hit it **in the air** and it takes a glancing blow — the touch fires
  its real mechanosensory JO (Johnston's organ) neurons, the same pathway
  that drives the giant fiber in a living fly, and it tumbles away
  (*swats dodged +1*)
- like a real fly it spends **most of its time sitting** (~70% when
  undisturbed, less as you close in), so there is always a target
- catch it **on the ground** and it's a SPLAT (*flies swatted +1*). Your
  approaching cursor looms on its retina and fires its escape circuit at
  ~110 px — but like a real fly, it then needs **100–220 ms to actually
  get airborne** (wings up, feet still down, buzzing in place). That
  startle window is your chance, and it is the entire reason flyswatters
  work on real flies too. Strike *through* where it sits, don't stalk it.
  A few seconds after the splat, another fly gets in through the window
  (fresh brain state, same connectome).

The HUD keeps score.

Stop the fly with `Ctrl-C` in the terminal that started it. If it ever
refuses to die, `pkill -f fruitfly` always works: it has no menu bar and no
`Cmd-Q`, because its windows are deliberately non-activating.

## Poke the circuit

With the fly running, type a population name into the terminal that started
it and press Enter. `GF` and it escapes; `MDN` and it scoots backwards;
`DNa02_L` and it turns that way; `?` lists all 35, including left/right
variants. Optional rate and duration: `LC4_R 150 1.0`.

Nothing about the reaction is scripted. The poke drives that population's
real neurons as a Poisson source, exactly the way the retina drives
photoreceptors, and what the body does next is the rest of the connectome
responding. Measured headlessly with the cursor 5,000 px away so nothing
visual could interfere: six two-second windows containing a `GF` poke
produced 10 escape-class events, and six windows without produced none.

The terminal is the input channel because the fly's windows are
deliberately non-activating — they never take keyboard focus — and reading
stdin needs no permission on any platform.

## Things to try

- Try to click the fly. Its mechanosensors fire and the giant fiber
  decides. Landed flies are easier targets — briefly.
- Rush your cursor at the fly: the looming response fires the giant fiber
  and it darts away (watch `GF` spike on the `--hud`).
- Sneak the cursor up slowly: much weaker looming drive — you can get
  closer before it bolts. This falls out of the circuit, it is not coded.
- Just leave it alone and watch: takeoffs, landings, saccades and startle
  hops arrive on the brain's own schedule.

## Honest science notes

What is real: the complete wiring diagram (every neuron, every connection
≥5 synapses, signed by predicted neurotransmitter), the LIF dynamics and
parameters of Shiu et al., the retinotopic eye maps, and the identity of
every circuit used — photoreceptors, lamina, LC4/LPLC2 looming detectors,
giant fiber, DNa02 steering neurons, DNp09, MDN, the descending pool.

**Corrected, not approximated.** Photoreceptors release histamine, which is
inhibitory, and that inhibition *is* the ON/OFF split. FlyWire's
neurotransmitter classifier has no histamine class and mislabels ~74% of
photoreceptor outputs as excitatory, so their outgoing sign is forced
negative at compile time. Without it the ON/OFF pathways are scrambled, so
this moves toward the real fly rather than away from it.

Approximated, and why:

- **Monoamines as fast excitation.** Dopamine, serotonin and octopamine are
  modelled as ordinary excitatory synapses. They are not: they act through
  GPCRs with slow, multiplicative effects, and serotonin's is broadly
  opposite to octopamine's. This is 1.97% of the connectome by synapse
  weight, octopamine alone 0.28%. Inherited rather than invented — Shiu et
  al. make the same simplification — but it belongs on this list.

- **Graded-neuron transduction.** Photoreceptors and lamina monopolar cells
  are non-spiking graded neurons, which a spiking LIF represents poorly.
  Their textbook transfer functions — adaptive phototransduction, and the
  lamina's transient OFF response — are computed in the sensory layer and
  injected at L1/L2/L3 per column. The real network begins at the lamina's
  *output* synapses, not at the medulla.

  That boundary still buys the ON/OFF split, which is wired rather than
  injected: L1's output is 99.6% inhibitory (glutamate and GABA) while L2's
  is 99.6% and L3's 99.8% cholinergic, so the sign inversion that builds the
  ON pathway is the real circuit's.

  Letting the OFF response emerge instead — biasing the lamina so real
  histamine inhibition is released by darkness — was measured and rejected.
  Photoreceptor input per lamina cell spans 6 to 128 synapses (5th to 95th
  percentile), so no single bias fits. Deriving it per neuron fixes that and
  still fails: Poisson shot noise on those inputs is ~6.7 mV against a 7 mV
  threshold gap, so a cell cannot tell darkness from a gap in its own input.
  And 28% of L1–L3 cells have no photoreceptor afferent at all. A spiking
  model cannot represent a graded synapse by discretising it; the fix would
  be graded transmission, not a cleverer bias.

- **Spike-frequency adaptation and a noise-floor governor.** Without them the
  model has only two states, coma and seizure. Adaptation is biologically
  standard; the governor is not — it raises an invented noise floor when the
  network falls quiet. Tempting to call that arousal, and this project used
  to, but octopamine multiplies drive that already exists, and multiplying a
  silent network leaves it silent. The governor sets a floor, a
  neuromodulator sets a gain, and only the floor keeps coma from being an
  absorbing state.

- **Exponential synapses at dt = 2 ms** instead of alpha synapses at 0.1 ms,
  calibrated to the same single-synapse PSP peak (0.275 mV). Decay factors
  are exact, `exp(-dt/tau)`, so dt costs spike-timing resolution without
  rescaling the time constants; `fruitfly benchmark` measures what your
  machine sustains. But dt is not purely a speed knob: finer steps resolve
  coincidences the coarse step merged, the network fires more, and the motor
  map was calibrated against the coarse rate — at dt=0.5 the fly stops
  landing (15.4 s of 30 landed at dt=2.0, 0.6 s at dt=0.5). Going finer
  needs `fruitfly calibrate`, which is why `--dt auto` will not do it for
  you.

- **A higher giant-fiber threshold and a rate-based motor readout.** The real
  GF is famous for its high threshold, and real motor circuits threshold
  their drive — but the wing motor neurons live in the ventral nerve cord,
  and this connectome stops at the neck. Turning descending rates into 2D
  screen motion is ours, and the least principled part of the project. It is
  also what makes it a desktop toy instead of a paper.

  That one is deliberate, not pending. The nerve cord is public: MANC is
  23,188 traced neurons including 379 wing and leg motor neurons, 76 MB of
  CSV, and the descending neurons read here (DNa01, DNa02, DNp01, DNp09)
  match it by name. But MANC is a male nerve cord and FlyWire a female
  brain. A chimera of two flies is not the complete real brain of a fruit
  fly, so the invented motor map stays.

Measured, not assumed (`python -m fruitfly phototaxis` / `padstats` /
`pipes`):

- **Luminance asymmetry does not steer this connectome.** One eye bright,
  one dim, mirrored so the reconstruction's own lopsidedness (5,790 left
  photoreceptors vs 5,361 right) cancels, over three brains. The
  1,305-neuron descending pool would have resolved a 3% lateral
  difference and measured 0.4%. So the fly is not drawn to bright
  things on screen, and nothing here will pretend it is.

- **Where the fly goes is decided by edge avoidance.** 120 simulated
  seconds replayed through the motor map on a 960×540 field: landed
  half the time, living in the lower-middle of the screen. A full-width
  pad on the bottom 20% gets hit ~4 times a minute — every hit a
  landing, never a slow flyover — while a thin 10% bar is never hit at
  all, because the fly turns back before it reaches the floor.

- **The loom detectors are selective, and the signal dies after them.**
  Six brains shown a dark obstacle through the eyes alone, with the
  LC4/LPLC2 injection switched off. An obstacle that *approaches* — one
  that grows the way a real one does — raises LC4 by 54%, in every
  brain. The same obstacle sliding past at constant size does not clear
  the noise, and one sitting still does nothing whatsoever. That
  selectivity is the real wiring's, not ours: nothing in the sensory
  layer knows what looming is. But the giant fiber downstream never
  moves, which is the honest reason the injection above exists — the
  eyes reach the detectors, and the detectors do not reach the escape.

- **It does not play Flappy Bird, and that is measured rather than
  assumed.** A fly in a chamber presses a plate; the plate flaps a bird
  through pipes. Over 60 rounds it beats a coin weighted to its own press
  rate in 50% of them — indistinguishable from chance — and beats doing
  nothing in 53%. The control that makes those numbers mean anything is a
  fourth arm that can see the gap: it clears 3 pipes on the same pipes, so
  the game is winnable and the fly simply does not win it. What the fly
  *does* do is startle, and 57% of its startles end with it on the plate:
  more than half its accidental button presses are escape reflexes.

## Tests

```bash
pip install -e ".[dev]"
pytest                    # everything, ~50 s
pytest -m "not slow"      # just the fast checks, ~3 s
```

One command runs all of it. Three suites drive the whole simulation for
tens of seconds each, so they carry a `slow` marker you can deselect;
anything needing `data/brain.npz` is skipped with a reason rather than
failed when there is none, so `pytest` on a fresh clone is green before
you have downloaded anything.

Those three are also plain scripts, because their output is a narrative
worth reading rather than a pass/fail — 30 seconds of a fly's life, or a
retina lighting up:

```bash
python3 tests/test_brain.py        # silence at rest, escape circuit, speed
python3 tests/test_behavior.py     # 30 s of closed-loop desktop life
python3 tests/test_behavior.py 0.5 # ... at a different timestep
python3 tests/test_retina.py       # retinotopy, and looming through the eyes
```

Coverage is **52%** (`coverage run --source=fruitfly -m pytest`). Most of
the remainder is code that cannot run headless on one machine: the three
window backends, `app.py` and `__main__.py`, which exist to wire the fly
to a screen, and the fetch/compile half of `data.py`. The parts that
decide how the fly behaves are where the coverage is — `senses` 100%,
`brain` 91%, `motor` 87%, `sprite` 86%.

## Layout

```
fruitfly/data.py      download + compile connectome & retinotopy (brain.npz)
fruitfly/brain.py     event-driven whole-brain LIF engine (numpy)
fruitfly/senses.py    retinotopic eyes: pixels -> photoreceptors & lamina
fruitfly/motor.py     descending neurons -> flight kinematics
fruitfly/sprite.py    the fly, and the splat when you get it, drawn in cairo
fruitfly/core.py      platform-independent controller + brain thread
fruitfly/ui/base.py   the Host interface a window backend implements
fruitfly/ui/gtk.py    Linux/X11 backend
fruitfly/ui/cocoa.py  macOS backend
fruitfly/ui/win32.py  Windows backend (ctypes, no dependency)
fruitfly/bench.py     what timestep this machine can actually sustain
fruitfly/calibrate.py re-derives the motor thresholds when the brain changes
fruitfly/experiments.py Phase 0 measurements (phototaxis, padstats, pipes)
fruitfly/export_web.py  brain.bin + the parity reference for the web port
fruitfly/app.py       wires brain + senses + backend together
fruitfly/__main__.py  the CLI: run, benchmark, calibrate, fetch, prepare,
                      test, phototaxis, padstats, pipes, export-web
web/                  the browser port: the same brain in TypeScript,
                      held to the Python one by a measured parity gate
tests/                backend contract, circuit, retina, closed-loop, tuning
```

Porting to another window system means implementing one class: five
methods (screen size, pointer, screen grab, move window, redraw) plus
event-loop wiring. `tests/test_backends.py` checks any backend against
the contract with a headless fake host.

Same idea, arrived at independently and in Swift:
[DenisSergeevitch/desktop-fly](https://github.com/DenisSergeevitch/desktop-fly)
— a 3D fly on the macOS desktop, also driven by a live spiking simulation of
the FlyWire connectome.

Data credit: [FlyWire](https://flywire.ai/) (Dorkenwald et al., Schlegel et
al., *Nature* 2024), used under its public data terms. Model design after
Shiu et al., *Nature* 2024.
