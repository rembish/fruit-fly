# fruit-fly 🪰

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
window layer is per-platform, in `fruitfly/ui/` (see
[`ui/base.py`](https://github.com/rembish/fruit-fly/blob/master/fruitfly/ui/base.py) for the interface a backend
implements).

| platform | backend | needs |
|---|---|---|
| Linux (X11, or Wayland via XWayland) | `gtk` | GTK3 + PyGObject, a compositing WM |
| macOS 10.15+ | `cocoa` | PyObjC, Screen Recording permission for vision |
| Windows 10/11 | `win32` | nothing extra (pure `ctypes`) |

All three have been run on real hardware. Linux is the one developed
against day to day; on macOS and Windows the fly is confirmed to appear,
fly, draw and quit, but the permission-gated vision path and the
click-through swatting have had little use, so reports are welcome.

Note that WSL is *not* a supported way to run this. WSLg gives X no
desktop to grab, so the fly is blind there, and its window fights the
Windows foreground; the app says so at startup and points at the native
Windows build.

**Linux** (Debian/Ubuntu/Mint):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-numpy
# first run downloads and compiles the brain (~50 MB, one time)
python3 -m fruitfly
```

**macOS** (Homebrew). Do not use the `python3` that ships with Xcode: it
is 3.9, which this project does not support, and pyobjc-core has no 3.9
wheel — pip falls back to a source build that fails on current clang.

```bash
brew install python@3.13 cairo pkgconf
python3.13 -m venv .venv
source .venv/bin/activate
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz pycairo numpy
python -m fruitfly
```

`pkgconf` is not optional: pycairo publishes no macOS wheels at all, so it
always builds from source, and its build finds cairo through pkg-config.
Installing cairo without it fails with "Dependency lookup for cairo with
method 'pkg-config' failed".

Stop the fly with `Ctrl-C` in the terminal that started it. If it ever
refuses to die, `pkill -f "fruitfly"` always works: the fly has no menu
bar and no `Cmd-Q`, because its windows are deliberately non-activating.

On first launch macOS will ask for **Screen Recording** permission —
that is the fly's eyesight (it reads the pixels around itself). Decline
and it still flies, just blind; grant it in System Settings → Privacy &
Security → Screen Recording and restart. No Accessibility permission is
needed: swat detection uses the window's own hit-testing.

**As a package**, once its dependencies are satisfied:

```bash
pip install fruitfly
fruitfly run
```

That works from a standing start on **Windows only**, where everything
needed ships a wheel. Everywhere else pip must build `pycairo` from
source — it publishes wheels for Windows and nowhere else, and PyGObject
publishes none at all — so the system libraries have to be there first:

| | pycairo wheel | what pip needs first |
|---|---|---|
| Windows | yes | nothing |
| macOS | no | `brew install cairo pkgconf` |
| Linux | no | distro `python3-gi python3-gi-cairo`, and a venv created with `--system-site-packages` |

On Linux the distro route above is not just the easier path, it is the
path: installing into a clean venv fails while building pycairo, with
"Dependency lookup for cairo with method 'pkg-config' failed".

**Windows** (PowerShell, Python from python.org):

```powershell
pip install numpy pycairo
python -m fruitfly
```

No extra dependency and no permission prompt: the window layer is pure
`ctypes` against Win32. The fly is a layered window, so clicks land only
on the fly itself and pass through everywhere else automatically —
Windows hit-tests layered windows per-pixel by alpha. On Windows 10
2004+ the fly is also excluded from screen capture, so it can't see
itself in its own retina.

Or install the package on any platform:

```bash
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -e .               # pinned versions in requirements.txt
fruitfly
```

Options:

```
fruitfly --hud          live neural telemetry overlay (GF/DNa02/LC4 rates)
fruitfly --size 48      bigger fly
fruitfly --pure-retina  no looming injection: escapes only via the real eyes
fruitfly --no-vision    don't sample the screen into the retina
fruitfly --noise 140    more spontaneous brain activity (a more annoying fly)
fruitfly --dt 1.0       finer integration (slower; default 2.0 ms)
fruitfly --backend gtk  force a backend (gtk, cocoa, win32); default: auto
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

Quit with Ctrl-C in the terminal. On Linux this needs a compositing
window manager for transparency (MATE: System → Preferences → Windows →
enable compositing); macOS and Windows always composite.

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
every input/output circuit used (photoreceptors, lamina, LC4/LPLC2 looming
detectors, giant fiber, DNa02 steering neurons, DNp09, MDN, the descending
pool).

What is corrected — not an approximation, a repair of a known defect in
the source data:

- **Histamine sign**: photoreceptors release histamine, which is
  inhibitory, and that inhibition *is* the ON/OFF pathway split. The
  FlyWire neurotransmitter classifier has no histamine class at all and
  so mislabels ~74% of photoreceptor outputs as excitatory. Their
  outgoing sign is forced negative during compilation. Without this the
  ON/OFF pathways are scrambled, so this moves the model toward the real
  fly rather than away from it. The principled generalisation, not done
  here, would be to take the neurotransmitter from curated per-cell-type
  literature wherever it is known and fall back to the classifier only
  otherwise.

What is added or approximated, and why:

- **Graded-neuron transduction**: photoreceptors and lamina monopolar
  cells are non-spiking, graded neurons in the real fly, which a spiking
  LIF model represents poorly (inhibition released onto a silent neuron
  produces nothing). Their textbook transfer functions — adaptive
  phototransduction, and the lamina's transient OFF response to local
  darkening — are computed in the sensory layer and injected at L1/L2/L3
  per column. The real network begins at the lamina's *output* synapses,
  not at the medulla.

  What that boundary still buys is more than it sounds. The ON/OFF split
  is not injected, it is wired: in the compiled connectome L1's output is
  99.6% inhibitory (glutamate and GABA) while L2's is 99.6% and L3's
  99.8% cholinergic. So the sign inversion that builds the ON pathway is
  the real circuit's, and it operates on whatever the injection feeds it.

  Letting the OFF response emerge instead — biasing the lamina cells to a
  depolarized point and letting real histamine inhibition be released by
  darkness — was measured and rejected. Photoreceptor input per lamina
  cell spans 5 to 111 synapses, so no single bias fits: the weakly-driven
  cells fire constantly and the strongly-driven ones never fire. A
  per-neuron bias derived from each cell's own afferents fixes that and
  still fails, because Poisson shot noise on those inputs is about 6 mV
  against a 7 mV threshold gap — the cell cannot tell darkness from a gap
  in its own input. And 30% of the L1-L3 cells have no photoreceptor
  afferent at all in the compiled graph, so those columns would go blind.
  The honest summary is that a spiking model cannot represent a graded
  synapse by discretising it; the fix is graded transmission, not a
  cleverer bias.
- **Background noise** (Poisson, central brain only): the connectome alone
  is silent — a network with no input never fires. Real brains have
  intrinsic noise and neuromodulation; ours is the source of all
  spontaneous behavior, but every "decision" still propagates through the
  real synapses.
- **Monoamines as fast excitation**: dopamine, serotonin and octopamine
  are modelled as ordinary excitatory synapses, like every other
  excitatory connection. They are not: they act through GPCRs with slow,
  multiplicative effects on gain and state, and serotonin's effect is
  broadly opposite to octopamine's. This is 1.97% of the connectome by
  synapse weight (octopamine alone 0.28%), and it is inherited rather
  than invented — Shiu et al. make the same simplification — but it was
  missing from this list, which is why it is here now.
- **Spike-frequency adaptation + slow noise-floor governor**: without them
  the model has only two states, coma and seizure (the paper only ever
  stimulates it for fractions of a second from silence). Adaptation is
  biologically standard and gives the network self-quenching bursts. The
  governor is not: it is a controller that raises the invented noise
  floor when the network falls quiet and backs it off when the network
  rages. It is tempting to call that arousal, and this project used to,
  but real arousal is neuromodulatory and could not do this job —
  octopamine multiplies drive that already exists, and multiplying a
  silent network leaves it silent. The governor sets a floor; a
  neuromodulator sets a gain. Only the floor keeps coma from being an
  absorbing state.
- **Exponential synapses, dt = 2 ms** instead of alpha synapses at 0.1 ms:
  calibrated to the same single-synapse PSP peak (0.275 mV). The decay
  factors are exact, `exp(-dt/tau)`, so dt costs spike-timing resolution
  but does not rescale the time constants. `python3 -m fruitfly benchmark`
  measures what your machine sustains. Note that dt is not purely a speed
  knob: finer steps resolve coincidences the coarse step merged, the
  network fires more, and the motor map was calibrated against the coarse
  rate — at dt=0.5 the fly stops landing altogether (landed 15.4s of 30s
  at dt=2.0, 0.6s at dt=0.5). Going finer needs a motor retune, which is
  why `--dt auto` will not choose it for you.
- **A higher giant-fiber threshold and rate-based motor readout**: the real
  GF is a huge neuron famous for its high threshold; and real motor
  circuits threshold their drive — but the wing motor neurons live in the
  ventral nerve cord, and this connectome stops at the neck. The final
  translation of descending-neuron rates into 2D screen motion is ours,
  and is the least principled part of the project. It is also the part
  that makes it a desktop toy instead of a paper.

  This one is deliberate, not pending. The nerve cord *is* public — the
  MANC connectome is 23,188 traced neurons including 379 wing and leg
  motor neurons, downloadable as 76 MB of CSV, and the descending neurons
  this project reads (DNa01, DNa02, DNp01, DNp09) match it by name, so
  the bridge would work. But MANC is a male nerve cord and FlyWire is a
  female brain. Wiring one to the other would buy a real motor readout at
  the cost of the sentence this whole project rests on: that you are
  watching one animal's brain. A chimera of two flies is not the complete
  real brain of a fruit fly. The invented motor map stays.

## Tests

```bash
pip install -e ".[dev]"
pytest                             # the fast checks, ~3 s, no brain needed
```

`pytest` collects what runs anywhere in seconds. Three suites are
deliberately *not* collected: they need the compiled connectome, take
tens of seconds, and are written to be read as much as run, so they are
plain scripts.

```bash
python3 tests/test_brain.py        # silence at rest, escape circuit, speed
python3 tests/test_behavior.py     # 30 s of closed-loop desktop life
python3 tests/test_behavior.py 0.5 # ... at a different timestep
python3 tests/test_retina.py       # retinotopy, and looming through the eyes
```

Coverage is **44%** from `pytest` alone and **53%** with the script
suites as well (`coverage run -a --source=fruitfly tests/test_brain.py`,
and so on). Most of the remainder is code that cannot run headless on one
machine: the three window backends, `app.py` and `__main__.py`, which
exist to wire the fly to a screen, and the fetch/compile half of
`data.py`. The parts that decide how the fly behaves are where the
coverage is — `senses` 100%, `brain` 91%, `motor` 87%, `sprite` 86%.

## Layout

```
fruitfly/data.py     download + compile connectome & retinotopy (brain.npz)
fruitfly/brain.py    event-driven whole-brain LIF engine (numpy)
fruitfly/senses.py   retinotopic eyes: pixels -> photoreceptors & lamina
fruitfly/motor.py    descending neurons -> flight kinematics
fruitfly/sprite.py   the fly, in cairo
fruitfly/core.py     platform-independent controller + brain thread
fruitfly/ui/base.py  the Host interface a window backend implements
fruitfly/ui/gtk.py   Linux/X11 backend
fruitfly/ui/cocoa.py macOS backend
fruitfly/ui/win32.py Windows backend (ctypes, no dependency)
fruitfly/app.py      wires brain + senses + backend together
tests/               circuit, retina, closed-loop and backend-contract tests
```

Porting to another window system means implementing one class: five
methods (screen size, pointer, screen grab, move window, redraw) plus
event-loop wiring. `tests/test_backends.py` checks any backend against
the contract with a headless fake host.

Data credit: [FlyWire](https://flywire.ai/) (Dorkenwald et al., Schlegel et
al., *Nature* 2024), used under its public data terms. Model design after
Shiu et al., *Nature* 2024.
