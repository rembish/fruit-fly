# A fly plays Flappy Bird — design notes for a web play mode

Status: design discussion, nothing built. This records the reasoning
before any code exists, so the code can be checked against it later.

The idea: put the fly brain in a browser and let it play a classic game.
It will lose constantly — that is not a bug in the plan, it is the
finding. This doc covers why the input is geometric (the fly lands on
buttons) rather than neural rate thresholds, why the game is Flappy Bird
rather than Mario or Tetris, why the web is a better home for this than
the desktop, and the two architectural decisions that make the port
smaller and sturdier than it first looks.

## Why the fly flies onto buttons

The README already names the least principled part of this project:
turning descending rates into 2D screen motion is ours, invented, and
what makes this a desktop toy instead of a paper. A game mode that reads
neural rates directly — "DNp09 above 12 Hz means JUMP" — would stack a
second invented mapping on top of the first, and a worse one: the 2D map
is at least continuous and defensible as descending drive → locomotion,
while a rate threshold on a keycode is pure fiat.

Buttons add *zero* new invented mapping. `MotorMap` already produces the
fly's position in screen coordinates; "is the fly's body inside this
rectangle" is a query on state we already compute. Nothing new is
asserted about the fly. We add a game, not a claim.

There is also a second-order payoff: the fly's eyes read real screen
pixels. A game rendered where the retina samples is genuinely in the
fly's visual input — the pipes scroll through its optic lobe. That is a
real closed loop, the only one in the project besides the cursor.

### Mechanics that follow from the fly we have

- **Edge-trigger, don't dwell.** A landed fly sits ~4 s. A held button
  would fire continuously; one press per arrival (with at most a slow
  auto-repeat) is better play and more thematically right — a fly
  *lands* on a button.
- **Ignore fast traversals.** An escape dart moves at 1400 px/s and
  crosses several buttons in one frame. Register a press only when the
  fly is landed or slow, or every startle produces a spurious chord.
- **Center bias is real.** The edge-avoidance in `motor.py` turns the
  fly back toward screen center, so edge buttons see less traffic than
  central ones. Either place the pad where the fly actually goes, or
  accept the asymmetry as part of the joke — but know it exists before
  reading anything into the score distribution.

## Say it up front: this fly cannot learn

There is no plasticity anywhere in the model. `brain.py` is fixed
connectome weights, LIF dynamics, adaptation and noise — no STDP, no
learning rule. The fly cannot get better at the game. Ever. Not slowly,
not with practice.

That is not a limitation to hide; it is the strongest framing available.
"A fly plays Flappy Bird" reads as brain–computer-interface hype, and
the Honest Science Notes exist precisely to refuse that register. But
"a fruit fly's connectome scores no better than chance at Flappy Bird,
and here is the measurement" is a real result, in exactly the register
of the GF poke measurement already shipped.

So the feature is a benchmark with three arms, not a game mode:

1. the fly,
2. a Poisson flapper rate-matched to the fly's own press rate,
3. do-nothing.

If the fly beats do-nothing, that is interesting and measurable. If it
does not beat Poisson, say so — that is the honest headline, and a
better one than any score. The comparison runs headless (Node) in CI
and its numbers get printed on the page itself.

## Why Flappy Bird

The selection criterion for a game a fly can "play": **doing nothing
must be a slow loss, and every input must be legal at any moment.**

Mario fails both — it needs a sustained right-hold plus jumps timed to
~100 ms, against a fly that sits ~70% of the time and moves in escape
darts. The result is a static screenshot of Mario standing still, then a
goomba, forever: four seconds of comedy, then a still image. Plus
ROM/emulator mess. Tetris is legal-at-any-moment but weak: four buttons
means being in the right one of four places, the board fills to a still
image while the fly sits, and one death takes minutes.

Ranked by fit: Pong/Breakout (paddle x = fly x, no buttons, no invented
anything — the paddle *is* the motor output), then Flappy Bird, then
Snake, then Tetris. Pong is the purest demo; **Flappy is the joke, and
the one this doc plans for**. One button — the entire input space is
"is there a fly on the pad". A fly flapping onto a pad to make a bird
flap is the gag, complete. And rounds last about three seconds, so a
visitor sees twenty deaths in the first minute — the correct comedy
density for a shareable page, versus one death per minute or two in
Tetris.

Design sketch:

- One big **FLAP pad** at the bottom of the play field; the fly buzzes
  around the canvas above it; contact while landed-or-slow = one flap,
  edge-triggered.
- The game is rendered where the retina samples, so the pipes loom in
  the fly's real optic lobe. Whether looming pipes fire LC4 and make
  the fly bolt — possibly *onto* the pad, an accidental save — is an
  emergent question the headless harness can answer.
- The visitor's cursor over the canvas still looms on the retina, as on
  the desktop, so spectators can sabotage the fly mid-run. Same
  interactivity, none of the permission text.
- A global "best fly ever" line — the longest flight any connectome
  instance has achieved on the site — is the one leaderboard where
  every entrant is the same brain. That is both the joke and the point.

### Open question to test before building the layout

Does this connectome do phototaxis at all? The loom pathway needed a
scaled-down direct LC4/LPLC2 injection because the emergent signal was
weak; steering toward (or away from) a bright pad requires DNa02 L/R
asymmetry to emerge from luminance asymmetry, and nothing in the repo
shows it does. The experiment is `test_retina.py`-shaped and headless:
bright patch on the left vs. the right, measure DNa02 asymmetry. Run it
*before* designing a layout that assumes attraction. If it comes out
null, buttons still work — hit by drift rather than attraction — and
the doc/README should say so.

## Why the web, and why the rewrite is smaller than it looks

The port is ~1,000 lines of the repo's most portable science code, in
exchange for deleting the need for its most painful 1,200:

| ports to JS/TS | dies instead of porting |
|---|---|
| `brain.py` (335 lines, typed-array math) | `ui/gtk.py`, `ui/cocoa.py`, `ui/win32.py` (~990 lines) |
| `senses.py` (192) | `app.py` (110) |
| `motor.py` (275) | screen-grab machinery in `core.py` |
| controller slice of `core.py` | all permission prompts |

The browser is the one window backend that runs everywhere. And the
permission story evaporates: desktop vision needs Screen Recording on
macOS and a compositor on Linux; a web page renders the game to a canvas
it owns, and `getImageData` on your own canvas needs no permission on
any platform. The retina reads the actual game pixels with less
machinery than `host.grab()` needs today. The closed loop gets *more*
real, not less.

(The desktop alternative was considered and rejected for games: driving
an external game window needs synthetic keystrokes, which on macOS means
Accessibility permission — breaking the README's explicit "no
Accessibility permission is needed" promise.)

## Architecture

### The big unlock: run the game on the brain's clock

The desktop fly must track a real cursor in real wall time. That single
obligation is why `bench.py` has a 1.05x realtime budget, why
`AUTO_MENU` is locked to dt=2.0, and why a machine sustaining 0.6x gets
a *broken* fly rather than a slow one — the motor thresholds are
calibrated against rates the slow sim never produces.

A game world has no such obligation. **Tie the game clock to sim time**:
pipes advance per simulated millisecond, not per wall millisecond. On a
slow phone the whole scene runs in slow motion — brain, bird, pipes
together — and the fly's behavior is identical to a fast desktop,
because nothing in the loop ever compares sim time to wall time. The
realtime constraint that dominates the desktop version's engineering
disappears. (It also reopens the multi-fly door the desktop's compute
budget closed: two flies at 0.5x is a valid, if leisurely, spectacle.)

### Browser performance: comfortable, no WASM needed for v1

From the repo's own numbers: the dense LIF update is ~139k neurons × a
handful of ops × 500 steps/s ≈ low hundreds of Mflops — trivial for a
`Float32Array` loop. Spike propagation: the dt=2.0 behavior test logs
12.4M spikes per 30 s ≈ 410k spikes/s, average out-degree 2.7M/139k ≈
19, so ~8M scatter-adds/s through a CSR. Plain JavaScript with typed
arrays handles this without WASM or WebGPU.

The brain runs in a **Web Worker** — the direct analog of
`BrainThread` — posting the motor-population rates to the main thread at
60 Hz. The rates dict is tiny, so plain `postMessage` suffices; no
SharedArrayBuffer, which matters because GitHub Pages cannot set the
COOP/COEP headers SAB requires.

Two porting paths were weighed:

- **Pyodide first**: numpy runs in WASM, so `brain.py` could run nearly
  verbatim in a worker as a proof of life. Costs ~20 MB of runtime
  download and likely 2–3x slowdown — which the sim-clock decision makes
  survivable. Good as a validation spike, wrong as the product.
- **TypeScript + typed arrays** as the real thing. Recommended.

### Parity with the Python reference

The TS port must reproduce the Python brain's behavior, and the motor
thresholds were calibrated against its rates. Spike-exact parity would
require porting numpy's exact RNG and is not worth it; the honest target
is **statistical parity on the rates the motor map actually reads**: run
N simulated seconds in Python and in JS from the same compiled brain and
compare per-population rate traces (GF, DNa02 L/R, DNp09, MDN,
descending pool) — the same style of check `tests/test_tuning.py`
already does. This runs in CI, which is the main reason the web code
belongs in this repo rather than a sibling project.

### Data delivery, and one license check

The web version cannot compile the connectome client-side; `prepare`'s
output gets precompiled into a web binary. Quantized — int32 CSR indices
(139,255 > 65,535, so int16 won't do), int16 signed weights (synapse
counts fit easily) — that is roughly 16 MB raw, likely 8–10 MB after
brotli. A loading bar that says *"downloading 139,255 neurons…"* is not
a cost, it is the opening joke.

To verify before hosting that file publicly: today the repo downloads
FlyWire CSVs from the source on first run, so the user compiles their
own copy; a web app means *we* redistribute a derived binary. Check that
the FlyWire/Codex data terms (citation required; some releases carry
NC-style conditions) permit redistributing a derivative from GitHub
Pages. Probably fine with attribution, but it is the kind of thing the
Honest Science Notes want settled, not assumed.

## A second mode worth keeping in mind: the human pokes, the fly plays

`poke()` already exists, is proven headlessly, and drives real
populations the same way the retina does. In a game context it becomes
QWOP-with-optogenetics: the player types (or taps) `DNa02_R` to nudge
the fly toward the pad, `GF` and it bolts across the board to parts
unknown. Indirect, laggy, unreliable control over an animal that is
nominally playing Flappy Bird — an *actual game* with a skill ceiling,
rather than a screensaver. The honest claim stays clean: not "the fly
plays", but "you can steer a real connectome badly enough to be funny",
which the poke measurement already backs. On the web this needs only
buttons that call the existing poke path.

That mode is the product; the fly-vs-Poisson benchmark is the paper.
Ship both.

## Repo shape and porting order

Keep it in this repo: `web/` with the TS brain, the game, and a small
Node headless harness. The compiled-brain format and the calibration
constants are shared truths between the Python and JS sides, and the CI
parity test only makes sense where both live. The desktop fly stays the
reference implementation; the web fly is the one people will actually
meet.

Porting order: **brain → parity test → senses/motor → game.** The game
is the easy part.

## Summary of decisions

1. Input is geometric (fly on a pad), never a neural rate threshold —
   no second invented mapping.
2. The fly cannot learn (no plasticity); frame the mode as a
   three-armed benchmark (fly / Poisson / nothing), not as "a fly
   playing".
3. Flappy Bird, for its one-button input space and three-second rounds;
   Pong is the fallback purest demo.
4. Web app in `web/`, TypeScript + typed arrays, brain in a Web Worker,
   no SAB, static hosting.
5. Game clock = sim clock. Slow machines get slow motion, never a
   miscalibrated fly.
6. Precompiled quantized brain (~8–10 MB compressed) — after checking
   FlyWire redistribution terms.
7. CI parity test against the Python reference on motor-population
   rates.
8. Before layout work: measure whether luminance asymmetry produces
   DNa02 asymmetry (phototaxis), headlessly.
