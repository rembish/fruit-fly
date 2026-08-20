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
terminal beside it logs the neurons firing behind each move](docs/demo.gif)

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
[`ui/base.py`](fruitfly/ui/base.py) for the interface a backend
implements).

| platform | backend | needs |
|---|---|---|
| Linux (X11, or Wayland via XWayland) | `gtk` | GTK3 + PyGObject, a compositing WM |
| macOS 10.15+ | `cocoa` | PyObjC, Screen Recording permission for vision |
| Windows 10/11 | `win32` | nothing extra (pure `ctypes`) |

**Linux** (Debian/Ubuntu/Mint):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-numpy
python3 -m fruitfly            # downloads + compiles the brain on first run
```

**macOS** (Homebrew):

```bash
brew install cairo             # pycairo needs it to build
pip3 install pyobjc-framework-Cocoa pyobjc-framework-Quartz pycairo numpy
python3 -m fruitfly
```

On first launch macOS will ask for **Screen Recording** permission —
that is the fly's eyesight (it reads the pixels around itself). Decline
and it still flies, just blind; grant it in System Settings → Privacy &
Security → Screen Recording and restart. No Accessibility permission is
needed: swat detection uses the window's own hit-testing.

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
  per column. Everything from the medulla onward is the real network.
- **Background noise** (Poisson, central brain only): the connectome alone
  is silent — a network with no input never fires. Real brains have
  intrinsic noise and neuromodulation; ours is the source of all
  spontaneous behavior, but every "decision" still propagates through the
  real synapses.
- **Spike-frequency adaptation + slow arousal homeostat**: without them
  the model has only two states, coma and seizure (the paper only ever
  stimulates it for fractions of a second from silence). Adaptation is
  biologically standard and gives the network self-quenching bursts.
- **Exponential synapses, dt = 2 ms** instead of alpha synapses at 0.1 ms:
  calibrated to the same single-synapse PSP peak (0.275 mV), traded for
  real-time speed.
- **A higher giant-fiber threshold and rate-based motor readout**: the real
  GF is a huge neuron famous for its high threshold; and real motor
  circuits threshold their drive — the wing motor neurons live in the
  ventral nerve cord, which is a separate connectome not included here.
  The final translation of descending-neuron rates into 2D screen motion
  is ours, and is the least principled part of the project. It is also
  the part that makes it a desktop toy instead of a paper.

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
