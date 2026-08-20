# fruit-fly-linux 🪰

A fly that lives on your Linux desktop, driven by the **complete real brain
of a fruit fly** — the [FlyWire](https://flywire.ai/) connectome of adult
*Drosophila melanogaster*: 139,255 neurons and ~34 million synapses, every
one of them mapped from an actual fly by actual scientists, simulated live
as leaky integrate-and-fire neurons while the sprite buzzes over your
windows.

No scripted behavior, no random walk. When the fly dodges your cursor it is
because your cursor was fed into its real looming-detector neurons (LC4,
LPLC2), which drove its real giant fiber escape neuron (DNp01) through real
synapses, exactly the circuit a living fly uses to evade your rolled-up
newspaper. When it takes off, lands, or jinks for no reason at all — a
neuron decided to.

## How it works

```
your screen ──► RETINOTOPIC EYES: 785+796 real eye columns, 9,199 mapped
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

## Install & run (MATE / any X11 desktop with compositing)

Dependencies: GTK3 via GObject introspection plus numpy. On Debian/Ubuntu/Mint:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-numpy
```

then, from the repo:

```bash
python3 -m fruitfly            # downloads + compiles the brain on first run
```

or install it:

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
fruitfly test           headless 30 s behavioral test, no window
```

Only a ~150 px transparent window travels with the fly — the rest of your
screen has no window over it, and within that window only the fly's body
accepts clicks. **Clicking the fly is a swat attempt**: the touch is fed
into its real mechanosensory JO (Johnston's organ) neurons — the same
pathway that drives the giant fiber in a living fly — and it escapes with
a realistic ~200 ms reaction time. Good luck. The HUD counts your misses.

Quit with Ctrl-C in the terminal. Requires a compositing window manager
for transparency (MATE: System → Preferences → Windows → enable
compositing).

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

What is added or approximated, and why:

- **Histamine sign correction**: photoreceptors release histamine
  (inhibitory), but the FlyWire NT classifier has no histamine class and
  mislabels ~74% of their outputs as excitatory. Their outgoing sign is
  forced negative during compilation — without this the ON/OFF pathways
  are scrambled.
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
fruitfly/app.py      transparent click-through GTK overlay + brain thread
tests/               circuit, retina-emergence and closed-loop tests
```

Data credit: [FlyWire](https://flywire.ai/) (Dorkenwald et al., Schlegel et
al., *Nature* 2024), used under its public data terms. Model design after
Shiu et al., *Nature* 2024.
