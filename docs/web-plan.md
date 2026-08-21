# Fruit Fly Arcade at fly.rembi.sh — the build plan

Status: approved plan, ready to build. The design reasoning lives in
[`docs/web-flappy.md`](web-flappy.md) and is adopted wholesale — this
document adds the decisions taken since, the deployment story, and the
work breakdown. When this plan and the design doc disagree, this plan
wins; when this plan is silent, the design doc governs.

Written 2026-08-21. Decisions confirmed with Alex the same day.

## Decisions taken (do not re-litigate)

1. **The site is the "Fruit Fly Arcade" — a hall of arcade cabinets,
   not one game.** The landing page at fly.rembi.sh is a cabinet
   selection screen; picking a cabinet takes you straight to that game
   with the fly playing it. A shared fly runtime (brain / senses /
   motor in a Web Worker) with games as pluggable modules behind a
   small `Game` interface. First cabinet: **Fruit Flappy Fly**
   (project code `fff`); **Pong and Tetris are the next cabinets**
   (Alex's pick — the design doc ranks Tetris the weakest fit for a
   fly, which makes it honest comedy, not a reason to skip it).
   Unbuilt cabinets stand in the hall dark and unplugged ("coming
   soon"). This repo is public and stays public — it's pure fun,
   nothing to hide.
2. **rembi.sh becomes a playground vitrine** (revised 2026-08-21,
   same day: the CRT terminal experiment retires — history keeps it,
   "one shell" may return as a card later). The site is a static
   cabinet of cards for Alex's silly projects, with a **residency
   model**: projects with their own domains get outbound cards
   (Deploy Tarot, Deploy Horoscope); domainless projects become
   **residents** — own Cloud Run service, own `name.rembi.sh`
   subdomain via the site's Cloudflare router Worker. **The Fruit Fly
   Arcade is born a resident at `fly.rembi.sh`**, deployed from THIS
   repo as its own static-nginx service. Plan of record for the site
   and the router: `~/work/rembi.sh/docs/plan.md` — this doc keeps
   owning the science, the game, and the fly's own service.
3. **Ingress: Cloudflare Worker → run.app** (the entryconditions
   pattern, Alex's newest project). No load balancer, no static IP,
   $0/mo extra, and Cloudflare's CDN caches the ~10 MB brain blob.
   Cloud Run service `rembi-sh` in project `rembish-main`,
   `europe-west3`, shared Artifact Registry `apps`, GitHub Actions via
   Workload Identity Federation. Explicitly rejected: full per-app LB
   (~$18/mo for a joke) and DNS-only domain mapping (no CDN in front of
   a 10 MB download).
4. **Science code lives here, in the fruit-fly repo, under `web/` —
   and so does the fly's deployment.** The Python brain stays the
   reference implementation; CI runs a statistical parity gate
   between the two. Tags `web-vX.Y.Z` build and deploy the fly's own
   nginx image to Cloud Run service `fruit-fly`; the only thing the
   rembi.sh repo holds is one router line (`fly.rembi.sh` → the
   run.app origin) and the vitrine card. No shared images, no bundle
   handoff — the cleanest possible seam.
5. **License is settled: FlyWire snapshot 783 is CC BY-NC 4.0.** A free
   joke site is non-commercial; redistribution of the compiled brain is
   fine **with attribution**. Ship a `DATA_LICENSE.md` next to the
   binary and an attribution section on the site. (Sources:
   codex.flywire.ai/faq, flywire.ai/guidelines.)
6. All architectural decisions from the design doc stand: geometric
   input (fly on a pad, never a rate threshold), the three-armed
   benchmark framing (fly / Poisson / do-nothing — this fly cannot
   learn), game clock = sim clock, TypeScript + typed arrays, brain in
   a Web Worker, plain `postMessage` (no SharedArrayBuffer, so no
   COOP/COEP anywhere), precompiled quantized brain.

## What NOT to do (constraints from the repos involved)

- No WASM, no WebGPU, no SharedArrayBuffer in v1. Typed-array JS is
  comfortably fast (design doc has the arithmetic), and the sim-clock
  decision makes slow machines a slow-motion fly, never a broken one.
- No new invented neural mappings. The only fly→game channel is
  MotorMap's screen position hitting a pad.
- No plasticity, no "the fly is learning" copy anywhere. The honest
  register of the README's Science Notes applies to every sentence on
  the site.
- Ops side (binding, from `rembish_org_ops/CLAUDE.md`): no per-app GCP
  projects, no Kubernetes/VMs, no replacing Cloud Run, no new paid
  services, no Terraform/IaC — manual `gcloud` runbooks are the house
  style. All GCP resources prefixed `rembi-sh-*` (dots are illegal in
  resource names).
- Don't copy `amifree` (separate GCP project — legacy exception).

## Repo A: `rembish/fruit-fly` — the science and the games

### Layout

```
web/
  package.json          # npm + committed lockfile, Node 22
  vite.config.ts        # Vite 7, MPA: hub + one entry per game; Vitest 4 config inline
  tsconfig.json         # strict: true, moduleResolution bundler
  src/
    brain/              # brain.ts, params.ts, rng.ts, loader.ts — DOM-free, framework-free
    senses/             # retina.ts, senses.ts
    motor/              # motor.ts (MotorMap port, same tuned constants)
    runtime/            # worker.ts, protocol.ts, controller.ts, simclock.ts
    games/              # api.ts (Game interface + registry), fff/ (then pong/, tetris/)
    ui/                 # canvas fly sprite, HUD, loading bar, poke panel
  pages/                # index.html (the cabinet hall), fff/index.html
  harness/              # Node headless: parity.ts, fff-bench.ts
  public/brain/         # brain.bin + meta.json + DATA_LICENSE.md (build artifact, gitignored)
fruitfly/export_web.py  # new CLI: python -m fruitfly export-web
```

Conventions (matching entryconditions where they fit): npm with
committed `package-lock.json`, Node 22, TypeScript strict, **no
ESLint/Prettier on the web side** — the gate is `tsc --noEmit` +
`vitest run`, colocated `*.test.ts` next to modules. Framework-free
vanilla TS: the whole app is canvases and a worker; nothing here needs
a component framework, and the hub is a static page. Comments explain
the trap, not the line (house style in every repo involved).

### Phase 0 — the two measurements (Python, headless, before any layout)

Both were mandated by the design doc; they are cheap and they shape
everything downstream.

- **M0.1 Phototaxis:** `tests/test_phototaxis.py`-shaped experiment:
  bright patch on the left vs the right of the retina, measure DNa02
  L/R rate asymmetry. If luminance asymmetry steers, the FLAP pad can
  be a bright beacon; if null (likely), pads are hit by drift and the
  site says so honestly. Either result is content for the Science
  Notes.
- **M0.2 Pad statistics:** do NOT re-simulate the brain — capture one
  descending-pool + position trace (~120 bio-s) once, then replay it
  through the ported/existing `MotorMap` offline with candidate pad
  rectangles (the `calibrate.py` replay technique; sweeps cost
  milliseconds). Measure: presses per minute, inter-press interval
  distribution, spatial occupancy heatmap (the edge-avoidance center
  bias is real — place the pad where the fly actually goes). Output
  feeds pad size/placement AND the Poisson arm's matched rate.

Acceptance: both experiments runnable via `python -m fruitfly` or
`tests/`, results recorded in the Science Notes section of the README
and echoed in this doc's changelog.

### Phase 1 — brain export, TS brain, parity gate

- **`python -m fruitfly export-web`** → `web/public/brain/brain.bin` +
  `meta.json`. Format v1, little-endian, versioned header:
  - `indptr` int32 (n+1; 2.7 M connections < 2^31 ✓ — the Python side
    is int64, downcast with an assert),
  - `indices` int32 (139,255 > 65,535, int16 won't do),
  - `weights` int16 signed summed synapse counts (assert
    `max |w| ≤ 32767` at export; widen to int32 if it ever fails —
    exc/inh gains and PSP calibration are applied at load time, same
    as Python),
  - all `pop_*` and `retina_*` arrays, and the meta (counts,
    format version, snapshot id, attribution).
  ≈17 MB raw, ~10 MB gzipped. Also export a **parity reference**:
  a seeded Python run's per-population mean rates as JSON.
- **`brain.ts`**: port `brain.py` 1:1 — exact exponential decay
  factors, the PSP calibration loop (deterministic; assert the TS
  constant matches Python's to 1e-6 in a test), adaptation, the GF
  +10 mV threshold shift, delay ring buffer, event-driven CSR
  propagation, the noise homeostat, `set_stimulus` Poisson forcing.
  RNG: mulberry32 (or xoshiro) — parity is **statistical**, spike-exact
  parity is explicitly a non-goal. Poisson sampling: Knuth for small λ,
  normal approximation above λ≈30 (the noise λ per step is in the
  thousands).
- **`harness/parity.ts`** (Node, no DOM): run 60 bio-seconds, seeded,
  noise 100 Hz — emit mean rates for GF, DNa02_L/R, DNp09, MDN,
  descending, plus network Hz/neuron and total spikes.
- **Parity tolerances by measurement, not by feel:** run the Python
  reference twice with different seeds; tolerance per population =
  1.5× the observed seed-to-seed spread. Small populations (GF is 2
  neurons) are noisy — 60 bio-s runs, and compare rates not spike
  counts. Network mean must sit at the homeostat's 1.0 ± 0.2 Hz.

Acceptance: parity gate green in CI; a `PERF` line in the harness
output (steps/s in Node) recorded but not gated.

### Phase 2 — senses, motor, runtime

- `retina.ts`, `senses.ts`, `motor.ts`: direct ports with the shipped
  tuned constants (LAND_REF 6.3, TAKEOFF_REF 8.8, thresholds, GF rate
  EMA τ 0.3 s / escape > 30 Hz / refractory 0.7 s — all documented in
  `motor.py`). Unit-test the motor state machine and pad edge-trigger
  logic in Vitest (pure functions, no canvas needed).
- **Thread split mirrors the desktop:** main thread = Controller
  (motor, game, rendering, retina *sampling* — `getImageData` on the
  offscreen world canvas at ~20 Hz sim time, patches posted as
  transferable Float32Arrays, ~1.4 MB/s); worker = BrainThread
  (senses.rates + brain.step + RateMonitor, posts `{rates, gfCount,
  simTimeMs}` at ~60 Hz).
- **Sim clock:** the worker free-runs capped at 1.0× wall time; the
  main thread advances the game world by the *simulated* ms it
  receives. Fast machine → realtime; slow phone → everything in slow
  motion together; the motor calibration never breaks. Nothing in the
  loop may compare sim time to wall time.
- **The fly cannot see itself:** the game world renders to an
  offscreen canvas (the retina's source); the visible canvas is
  world + fly sprite composited. Same principle as the desktop's
  capture-exclusion, zero permissions.
- Spectator cursor over the canvas is rendered into the retina with
  the same perspective looming as the desktop — sabotage stays.

### Phase 3 — the Game API and Fruit Flappy Fly

- `games/api.ts`: `Game { id, name, command, init(ctx), tick(simDtMs),
  drawWorld(ctx2d), pads(): Pad[], onPress(padId), score, over }` plus
  a registry the hub (and the vitrine card list) reads. The runtime owns: fly
  state, pad registration, **edge-triggered press detection** (press
  only when landed-or-slow; one press per arrival; a 1400 px/s escape
  dart crossing a pad registers nothing), poke panel, HUD.
- `games/fff/` — Fruit Flappy Fly: one big FLAP pad at the bottom,
  pipes advancing per sim-ms, ~3 s rounds, instant restart. Score =
  pipes + flight time. "Best fly ever" in `localStorage` first
  (global board is Phase 6).
- **Poke mode ships with it** (the design doc's "QWOP-with-
  optogenetics" — that mode is the product): buttons driving the real
  populations (`GF`, `DNa02_L/R`, `DNp09`, `MDN`…) through the
  existing stimulus path.
- Landing page: **the cabinet hall** — Fruit Fly Arcade rendered as a
  row of arcade cabinets, one per game. fff's cabinet is lit and
  playable; Pong and Tetris cabinets stand dark/unplugged until they
  exist. The honest framing up top, attribution + CC BY-NC notice,
  link to the rembi.sh vitrine (when it exists). Loading bar reads
  "downloading 139,255 neurons…".
- Aesthetic: arcade-cabinet world — the direction is set (cabinets,
  hall, insert-coin energy); the execution and art are the builder's
  call.

### Phase 4 — the benchmark (the paper half)

- `harness/fff-bench.ts`: headless Fruit Flappy Fly, three arms — the fly,
  a Poisson flapper rate-matched to the fly's measured press rate
  (from M0.2, re-measured live), and do-nothing. ~200 rounds per arm
  locally (make target), a ~20-round smoke in CI. Output JSON with
  medians and CIs.
- The numbers get printed **on the page itself** and in the README
  Science Notes. If the fly does not beat Poisson, that is the
  headline. Also answer the emergent question: do looming pipes fire
  LC4 and cause accidental pad-saves? (Instrument escapes-onto-pad.)

### Phase 5 — CI, the fly's own service, going live at fly.rembi.sh

- Extend `.github/workflows/checks.yml`:
  - `web` job (every push/PR): Node 22, `npm ci`, `tsc --noEmit`,
    `vitest run`, `vite build`, bundle-size budget check (fail if the
    non-brain bundle balloons past ~2 MB gz; the brain is budgeted
    separately at ~12 MB gz).
  - `web-parity` job: reuse the existing connectome cache key
    (`connectome-${{ hashFiles('fruitfly/data.py') }}`), `python -m
    fruitfly export-web`, then the Node parity harness + benchmark
    smoke.
- **The fly deploys itself.** New in this repo:
  - **`web/Dockerfile`**: build stage runs `export-web` (connectome
    from the CI cache) + `vite build` → `nginx:alpine`, site at
    `/usr/share/nginx/html/`, `EXPOSE 8080`.
  - **`web/nginx.conf`** (base: entryconditions' — the cleanest):
    `listen 8080`; `/ping` health endpoint (**not** `/healthz` — GFE
    reserves it on Cloud Run); security headers with `always`; CSP
    `default-src 'self'` **plus `worker-src 'self'`** (the brain
    worker dies without it — entryconditions' own config lacks this,
    noted gap); hashed assets and `brain.bin` (hash-named) at
    `max-age=31536000, immutable`; `gzip_static on` with the brain
    pre-gzipped at build; `DATA_LICENSE.md` served alongside.
  - **`.github/workflows/deploy-web.yml`** (model: `tripclimate_com`
    single-service + `portolanmap_com` safety steps): `on: push:
    tags: ['web-v*']`; check job re-runs the web + parity gates;
    deploy job with `permissions: {contents: read, id-token: write}`,
    `google-github-actions/auth@v2` (WIF secrets), build+push to
    `europe-west3-docker.pkg.dev/rembish-main/apps/fruit-fly`,
    `gcloud run deploy fruit-fly --no-traffic --tag=smoke`, curl
    smoke against the `smoke---` revision URL (`/ping`, `/`,
    `/brain/meta.json`), `update-traffic --to-latest` on success +
    Cloudflare cache purge (skip gracefully if secrets unset),
    `--remove-tags=smoke` rollback path on failure.
  - Web version lives in `web/package.json`; the `web-v*` tag must
    match it (CI-asserted). Desktop versioning
    (`fruitfly/__init__.py`) is untouched.
- The fly serves from its subdomain **root** — no base-path flag, no
  `/fly/` prefix anywhere in the app.

## Repo B: `rembish/rembi.sh` — the vitrine and the router

Full detail lives in `~/work/rembi.sh/docs/plan.md`; the contract
between the repos is exactly two lines wide:

- **The router Worker** (in the rembi.sh repo) maps `fly.rembi.sh` →
  this repo's `fruit-fly-<hash>.a.run.app` origin, plus one proxied
  DNS record in the zone.
- **The vitrine card** for the Fruit Fly Arcade links to
  `https://fly.rembi.sh`, shown as *hatching* until the service is
  live. **The vitrine comes later** — fly.rembi.sh is the active
  front; until the vitrine ships, the router answers the apex
  (`rembi.sh`) with a redirect to `fly.rembi.sh`. Neither repo's
  release ever redeploys the other.

## One-time ops (manual, run by Alex or with him watching)

In order, from `SHARED-GCP-RUNBOOK.md` / `REMBISH-DEPLOY-RUNBOOK.md`
(skip DB/secrets/migrate steps — static site):

1. **WIF**: the provider's `attribute-condition` is an `||` chain that
   must be **appended to, not recreated** — read the current live
   condition first, then re-issue with
   `|| assertion.repository=='rembish/rembi.sh'
   || assertion.repository=='rembish/fruit-fly'` appended (both repos
   deploy now), plus the matching `add-iam-policy-binding` for each
   `principalSet://…/attribute.repository/rembish/<repo>`
   (`roles/iam.workloadIdentityUser`). Secrets in BOTH repos:
   `WIF_PROVIDER` =
   `projects/224907267272/locations/global/workloadIdentityPools/github/providers/github-provider`,
   `WIF_SERVICE_ACCOUNT` = `github-actions@rembish-main.iam.gserviceaccount.com`.
2. First image pushes + `gcloud run deploy <service> --port=8080
   --allow-unauthenticated --min-instances=0 --memory=128Mi` for
   `rembi-sh` and `fruit-fly` (entryconditions runs static nginx at
   128 Mi happily; bump the fly's later only if measured).
3. **Cloudflare**: create zone `rembi.sh` in the account (nothing is
   provisioned today — the ops repo has zero mentions of it),
   delegate nameservers at the registrar (registrar unknown — Alex
   knows where the domain lives). Deploy the **router Worker** from
   the rembi.sh repo (start from
   `entryconditions/cloudflare/worker.js` — Free plan can't rewrite
   Host — generalized to the ORIGINS hostname→origin table; routes
   `rembi.sh/*` and `*.rembi.sh/*`; proxied DNS records for the apex
   and `fly`), SSL/TLS **Full (strict)**. Cache rule: cache
   `fly.rembi.sh/brain/*` aggressively (immutable, hash-named). Repo
   secrets for the purge step: `CLOUDFLARE_ZONE_ID`,
   `CLOUDFLARE_API_TOKEN`.
4. Update `rembish_org_ops/docs/` inventory with the new services,
   worker, and zone (public/private split: runbook copy in the public
   repo, inventory in ops).

## Phase 6 — later, explicitly optional

- **Global "best fly ever"**: a tiny Cloudflare Worker + KV
  (`entryconditions/cloudflare/feedback/` is the precedent: KV
  rate-limit, `wrangler secret put`). Scores are client-reported —
  clamp to plausibility, rate-limit, and say on the page that the
  leaderboard is decorative. Every entrant is the same brain; that's
  the joke and the point.
- **More cabinets** — committed next: Pong (paddle x = fly x — the
  purest, zero pads) and Tetris (four pads; the design doc's honest
  warning stands: the board fills to a still image while the fly
  sits, and that IS the joke). Candidates after: Breakout, Snake.
  Each is a `Game` implementation + a lit cabinet in the hall; the
  runtime does not change.
- Sound → JO neurons; multi-fly spectacle (the sim-clock decision
  reopened that door). A gusty breeze belongs on the same shelf: wind
  is sensed by the same organ (Johnston's, antennal deflection), so it
  is the same injection machinery. Gusts, not a constant flow — this
  brain responds to events, not conditions, and anything steady adapts
  away within seconds (the M0.1 lesson). Expect startle texture, not
  anemotaxis: wind-following in real flies is odor/state-gated through
  central-complex machinery this LIF does not sustain.

## Changelog — what the phases actually measured

### Phase 0, 2026-08-21: both mandated measurements done

Code: `fruitfly/experiments.py`, `python -m fruitfly phototaxis` and
`python -m fruitfly padstats`, decision logic pinned in
`tests/test_experiments.py` (no connectome needed, so it runs in the
fast CI job).

**M0.1 phototaxis — NULL, and cleanly.** Luminance asymmetry does not
steer this connectome. Three brains (seeds 7/11/13), one eye at 0.85
luminance and the other at 0.15, then mirrored, eyes only — no loom
injection, no cursor.

The design is a difference of asymmetries, not a stimulus-vs-baseline
comparison, because the reconstruction is itself lopsided: 5,790 left
photoreceptors against 5,361 right (8%), 54 LC4 against 50. A single
"bright on the left" run showing more right-side drive would have
measured that, not phototaxis. Both mirror images are run and
`asym(bright_L) − asym(bright_R)` is the result, so any fixed structural
bias appears in both terms and cancels. A sham pair of two identical gray
epochs, put through the same arithmetic, gives the noise floor.

| readout | window | effect | needs (1.5× sham SD) | verdict |
|---|---|---|---|---|
| DNa02 | transient | −0.2487 | 1.0110 | null |
| DNa02 | sustained | +0.0032 | 0.2401 | null |
| descending | transient | +0.0037 | 0.0279 | null |
| descending | sustained | −0.0024 | 0.0292 | null |

DNa02 is one neuron per side and its sham SD (0.67 on the transient
window) says so — that pair alone could not have detected anything short
of an enormous effect. The 1,305-neuron descending pool was added as the
high-SNR corroboration and is what makes the null worth stating: it
would have resolved a 3% lateral difference and measured 0.4%.

Consequences, binding on Phase 3: **the FLAP pad cannot be a beacon.**
No bright-pad attraction, and nothing on the site may imply the fly is
aiming at anything. Pads get hit by drift, and layout follows M0.2's
occupancy map — where the fly already goes — rather than where we would
like it to look.

**M0.2 pad statistics — the bottom pad works at h=20%, and every press
is a landing.** One 120-second capture of descending drive + GF spikes
(seed 7, blind and unthreatened, the `calibrate.py` operating point),
replayed once through the real `MotorMap` on a 960×540 field; each
candidate pad is then a geometry query on that one trajectory. The fly
was landed 50% of the time at a mean speed of 165 px/s, and edge
avoidance shapes everything: time per horizontal band, top to bottom,
is 11.9% / 10.4% / 23.7% / 31.1% / 22.9% — the fly lives in the lower
middle, not on the floor.

Presses are edge-triggered arrivals ("inside the pad and landed or
slow", rising edge only), swept over three definitions of slow:

| pad (canvas fractions) | landed only | ≤60 px/s | ≤120 px/s |
|---|---|---|---|
| bottom full, h=10% | 0.0/min | 0.0 | 0.0 |
| bottom full, h=20% | 4.0/min | 4.0 | 4.0 |
| bottom full, h=30% | 4.5/min | 4.5 | 4.5 |
| bottom mid-60%, h=20% | 3.5/min | 3.5 | 3.5 |
| centre band, h=20% (control) | 2.5/min | 2.5 | 2.5 |

Decisions, binding on Phase 3:

- **The FLAP pad is full-width, bottom 20% of the canvas.** The
  obvious-looking thin bar is the one that fails: at h=10% the pad got
  zero presses in two minutes, because edge avoidance turns the fly
  around before it reaches the floor. h=30% buys +0.5/min for half
  again more screen — not worth it. Narrowing to the middle 60% loses
  presses (3.5/min); full width wins.
- **The press predicate is landed-only.** The rate is identical across
  all three slow thresholds for every candidate: every press is a
  landing, and the slow clause adds nothing. The web runtime pins
  "press" to the landed state and drops the speed clause.
- **The Poisson arm's matched rate is ≈4 presses/min** (inter-press
  p10/50/90 = 3.2/13.8/25.8 s — read with respect, that is 8 presses).
- **These numbers hold at 960×540 only.** The motor map's speeds and
  its 24 px edge margin are absolute pixels; a bigger canvas means
  proportionally less of it crossed per second and a fatter centre
  bias. Phase 3 builds at this size or re-measures (`--canvas W H`
  makes that one command).

### Phase 0 addendum, 2026-08-21: M0.3, pipes through the eyes

Code: `python -m fruitfly pipes`, decision logic in
`tests/test_experiments.py` alongside the other two.

M0.1's null is the biologically expected answer to the question it
asked — a brightness held still for seconds is nearly a null stimulus
for a visual system built around change. The trigger a real fly uses
is *motion*, and the one visual behaviour this connectome produces
from pixels alone is escape from a looming edge. So the question fff
actually needs is not "is the fly drawn to the pad" but "does an
approaching pipe reach the giant fiber" — which decides a rendering
choice, because a flat side-scroller translates a pipe of constant
size while a perspective one grows it, and those are different stimuli
to an optic lobe.

Six brains, eyes only (`loom_injection=0.0` — the direct LC4/LPLC2
injection exists to paper over a weak emergent signal, and leaving it
on would have measured the safety net). A real pipe pair, dark wall
with a gap, at `test_retina.py`'s contrast. Four conditions against a
blank pair for the floor: **static** (parked — M0.1's control in
pixels), **scroll** (flat renderer, crossing at 150 screen px/s),
**loom** (perspective, growing 0.4× → 3.2× head-on).

| condition | LC4 | giant fiber (rate) | GF burst | descending |
|---|---|---|---|---|
| static | −3.0% → null | +4.4% → null | −3.2% → null | +0.3% → null |
| scroll | +9.7% → null | +4.4% → null | −6.4% → null | −0.6% → null |
| loom | **+53.7% → drives** | +16.3% → null | +9.1% → null | +1.0% → null |

**The loom detectors see the pipe, and nothing downstream does.** LC4
rises from ~0.47 Hz at blank to 0.69–0.82 Hz on an approach in *every
one of six brains*, and the selectivity is textbook: expansion drives
it, a flat sweep of the same pipe does not clear the bar, a parked
pipe does nothing at all. That is a loom detector behaving like a loom
detector, out of the real wiring, from pixels alone. But the giant
fiber never moves — +16.3% against a bar of 2.4 Hz it misses, and the
per-approach burst statistic misses too — and neither does descending
drive. The eyes alone do not command an escape.

Consequences, binding on Phase 3:

- **Render pipes with perspective.** Expansion is the only thing that
  moves the visual circuit at all; a flat sweep is, to this optic
  lobe, nearly the same as a parked pipe.
- **The flap cannot be a pure-retina escape.** fff rides the disclosed
  LC4/LPLC2 injection to turn an approach into a startle, exactly as
  the desktop fly does with the cursor. That is a real coupling and an
  honest one *provided the site says so* — the Science Notes already
  disclose the injection, and the fff page must not claim the fly
  escapes pipes it can only half-see.
- **If Phase 3 wires vision in, M0.2 must be re-measured.** Its press
  statistics are explicitly the blind, unthreatened floor; startle
  darts at 1400 px/s cross a pad without landing, and the press
  predicate is landed-only.
- A side-view canvas changes nothing by itself: the brain has no
  gravity sense and the motor map no concept of up. The lever is world
  motion, which any camera angle can render.

Two honesty notes. An earlier fixed-order pilot had the flat scroll
clearing the bar at +11.8%, where this run reads +9.7% and null — but
the credit does not go to counterbalancing specifically. The effect
itself barely moved (0.055 → 0.046 Hz); what changed the verdict is
that the bar doubled (0.049 → 0.095), because the noise floor was
re-measured with six brains and with gaps long enough for adaptation
to recover. Rotation, seed count and gap length all changed in the
same rerun, so which of them mattered cannot be separated here. What
can be said is that the scroll effect was never robust and the loom
effect survived every version of the design. Second: the blanks always
run first, so a global drift would inflate every condition equally and
rotation cannot remove that — **static is the sentinel**, and it stays
null, so drift is not the story.

LPLC2 is reported as too quiet to judge throughout. It sits near
0.05 Hz, its sham spread collapses to 0.004, and at that point
arithmetic clears any margin and reads as biology.

### Phase 1, 2026-08-21: export, port, parity gate green

Code: `python -m fruitfly export-web`, `web/src/brain/`,
`web/harness/parity.ts`, CI jobs `web` and `parity`.

**brain.bin is 17.1 MB in 48 sections** — a magic, a JSON directory,
then the raw little-endian arrays, each on an 8-byte boundary so the
browser can build TypedArray views on the download without copying. All
three narrowings hold with room: 2.7 M connections against int32's
2.1 G, and weights are whole synapse counts in [−2405, 1897] against
int16's 32,767. The export refuses a fraction or an overflow rather
than wrapping one, and reads its own output back before claiming to
have written it. Retina arrays ship now, so Phase 2 needs no format
bump.

**The port passes on the first run.** Five seeds, 60 bio-seconds each,
resting network, no stimulus:

| readout | TS | Python | tolerance | |
|---|---|---|---|---|
| network Hz/neuron | 1.5908 | 1.5907 | 0.0137 | ok |
| descending (1305) | 5.7813 | 5.7523 | 0.0373 | ok |
| central (32381) | 5.0795 | 5.0781 | 0.0544 | ok |
| DNa02_L (1) | 24.343 | 24.357 | 0.825 | ok |
| GF (2) | 3.360 | 3.143 | 0.568 | ok |
| LC4 (104) | 0.0707 | 0.0740 | 0.0118 | ok |

The PSP calibration — the one constant both runtimes derive rather than
read — agrees to zero at printed precision, not merely to the 1e-6 the
plan asked for. `descending` is the tightest pass (0.029 against 0.037)
and is the row to watch if the port is touched again.

**Two corrections to this plan, both measured.** The tolerance
procedure said "run the Python reference twice"; a spread from one
degree of freedom can come out near zero by luck, and GF is two
neurons. Five seeds, and the gate treats a zero-spread readout as
unpoliceable rather than as infinitely strict — otherwise it is a bar
no implementation clears, including the one that set it. And the plan
asserted the network sits at the homeostat's 1.0 ± 0.2 Hz. It does
not: it sits at **1.59 with the governor emptied to 0.00 Hz**. The
governor's only lever is *adding* noise, and this network is livelier
than its target on recurrence alone, so the loop bottoms out within ten
simulated seconds and has nothing left to do. It prevents coma; it
cannot prevent liveliness. Gating on the target would have failed a
correct port for disagreeing with an incorrect expectation, so the gate
compares the port to the measurement — and compares the governor's own
resting value too, since two runtimes whose rates matched while their
governors sat elsewhere would be agreeing by luck.

**PERF, recorded and not gated: 339 steps/s in Node, 0.68× realtime at
dt=2** on the development machine. Under realtime, single-threaded,
before any browser is involved. Phase 4 owns this, but the number says
now that the sim-clock decision — the worker free-runs and the game
advances by simulated ms — is load-bearing rather than decorative.

Nothing here is visible in a browser yet, by design: Phase 1 is the
brain and its gate, both headless. The first thing to look at is
Phase 2 (a fly moving on a canvas) and the first thing to *play* is
Phase 3.

### Phase 2, 2026-08-21: it flies in a browser

Code: `web/src/senses/`, `web/src/motor/`, `web/src/runtime/`,
`web/index.html`, harnesses `sense-parity.ts` and `smoke.ts`.

`npm run dev` and the fly is on a canvas, its body driven by 139,255
neurons in a worker, at **0.4–0.6× realtime** on this machine. It sees
the pointer, and it bolts from it.

**The sim clock works and is visible.** The worker free-runs capped at
1×, posts `simTimeMs`, and the body, the world and the retina cadence
all advance by that number. The 1× cap in the worker's scheduler is the
only comparison of simulated time to wall time anywhere in the runtime.
The worker yields between chunks with `setTimeout` rather than looping —
a tight loop never receives a patch message, and the symptom is a blind
fly that reads as a retina bug.

**Two gates were added that the plan did not ask for, both because
Phase 1's gate cannot see this phase.** `sense-parity` holds both eyes
at a fixed luminance and compares the same populations: TS 5.65 Hz
against Python's 5.84 on a dark field, 5.70 against 5.63 on grey. Phase
1's gate runs with *no stimulus*, so it is blind to a fault in the
retina, the column mapping, or the way six thousand per-neuron rates
reach `setStimulus` — and that is most of what Phase 2 added. `smoke`
drives the real page in a headless browser and asserts on what the fly
does. It earned its place immediately: the first run failed on a 404 for
the entry module, which every other check passed straight through.

**A finding with teeth for Phase 3: vision swings the descending pool
hard.** Blind, it sits at 5.75 Hz; on a flat field with the eyes open,
5.65; flying through a moving scene it ranges **3.2 to 12.2 Hz**. Every
edge crossing the retina is a darkening transient and L1's output is
99.6% inhibitory, so a fly with something to look at is a fly whose
arousal is being modulated by what it sees. This is the plan's "M0.2
must be re-measured with vision on" clause coming due with a number
attached: `LAND_REF` is 6.3 and `TAKEOFF_REF` 8.8, and a pool that
wanders across both of them behaves nothing like one that idles between
them. **Phase 3 re-measures padstats against its actual scene** before
trusting the 4 presses/minute figure.

**One deviation from the layout above:** the pages live at the package
root (`web/index.html`, later `web/fff/index.html`) rather than under
`pages/`. Vite normalises a `../src/...` script reference away to
`/src/...`, which 404s in dev, and the failure shows as a page stuck on
its loading bar with a single failed request. Root-level HTML is the
conventional Vite MPA layout and each file's URL is its path.

Still Phase 3's: the Game API, pads on screen, fff itself. The pad
*rule* is already here and tested — landed-only, edge-triggered, one
press per arrival — because M0.2 decided it and the plan puts those
tests in this phase.

### Phase 3, 2026-08-21: fff, in both modes, before choosing either

Code: `web/src/games/api.ts`, `web/src/games/fff/`, `web/fff/index.html`.
Live at `/fff/`, with the mode switchable while it runs.

The design doc's game is the **controller** mode and it is worth
restating plainly, because this plan drifted from it: *the fly is an
input device*. A bird falls under gravity and flaps when, and only when,
the fly lands on the FLAP pad. The fly is not playing anything and does
not know a game exists. That is the joke, and the doc's headline was
never "a fly plays Flappy Bird" — it was "a fruit fly's connectome
scores no better than chance at Flappy Bird, and here is the
measurement", which is why the flapper is swappable between the fly, a
Poisson process rate-matched to the fly's own press rate, and nobody.

The **pilot** mode is the other reading, and it is a different claim:
the fly *is* the bird, no pad and no proxy, its own body has to be in
the gap. Nothing aims it — M0.1 established it does not steer toward
anything — so it is not a game it can win. It is a way of watching what
a connectome does when a wall arrives, which M0.3 measured at the
population level and this shows at the whole-animal one. Both are built;
neither is chosen here.

**What the first runs show.** Controller mode: the bird sits on the
floor. At M0.2's measured ~4 pad arrivals a minute the fly supplies one
flap every fifteen seconds, against a bird that needs one every 0.68 s
to hold its height — a factor of twenty-two. It is not close, and it is
not a tuning failure to be fixed by softening gravity: softening it
until the fly looks competent would be inventing the result the doc
exists to refuse. Pilot mode survives longer (about 2 s against 0.8 s)
purely because a fly that wanders is harder to hit than a bird that
falls.

**The confound is now a switch.** The game is drawn into the canvas the
retina samples, as the doc requires, so the pipes really do loom in the
fly's optic lobe — and Phase 2 measured that a moving scene swings the
descending pool 3.2–12.2 Hz, which moves the fly's landing behaviour and
therefore its press rate. The Poisson arm has no such coupling. `pipes
in the fly's eyes: off` gives the same fly the same pad and a scene it
cannot see, which is the control that comparison needs.

Still open, and deliberately not decided: which mode is the cabinet, and
whether the three arms run headless in CI with their numbers printed on
the page (the doc asks for that; it needs padstats re-measured against
this scene first, per Phase 2's finding).

### Phase 3 addendum, 2026-08-21: the chamber, and what it cost

Six corrections from watching it run, all of them things no test caught.

**The fly is in a chamber now**, on the left, split across the middle:
the lower half flaps the bird, the upper half does not. That is what an
input device is physically. `MotorMap` grew a `bounds` rect for it.

**The plate started as a ledge on the chamber floor and measured zero
presses in 26 simulated seconds.** The desktop fly is a *top-down*
animal — `LANDED` means feet down on the surface, and the surface is the
whole plane, so it sits wherever it stopped. There is no gravity in the
motor map and there never was. A ledge at the bottom is a place it never
goes.

**Edge-triggering alone is not enough here.** A single press on arrival
threw away the entire time the fly spent standing on the plate: one flap
per eleven seconds against a bird needing one every 0.68. The plate now
repeats every 0.3 s while held. That is the one number chosen for
playability rather than measured, and it is applied identically to all
three arms, so the comparison between them is untouched.

**Walls bounce instead of killing.** Almost every round was ending on
the ground before a pipe was reached, so the game the page claims to
measure was never being played.

**The bird's runway was set by the timetable, not the flapper.** Every
arm died at the identical second — the first pipe's arrival — until the
pipe field grew a lead-in.

**The scene control is not established.** The game is drawn where the
retina samples, and the chamber glass was being painted *over* the pipes
at 55% opacity, dimming the one thing the fly was meant to see; drawing
it underneath fixed that. But the coupling still does not reproduce:
descending drive is unmoved either way (5.74 vs 5.77 Hz), and press rate
came out 73 vs 74 per minute in one pair of runs and 67 vs 146 in the
next. Single short runs cannot separate that from drift. **The honest
state is "unknown", and settling it needs the repeated headless
comparison the design doc already asks for** — not another look.

**Where it stands: the fly cannot play.** Across fly, Poisson and
nobody, best score 0 and rounds ending on the first pipe. That is the
doc's predicted headline arriving on schedule, but it is not yet a
result: three single runs at one seed is an anecdote. The measurement it
deserves is the headless three-arm comparison, and that is the next
piece of work rather than anything on the page.

### Phase 3 fix, 2026-08-21: the background-tab fast-forward

Reported from a real browser: leave the tab in the background, come
back, and the game runs "extra boosted". It was a bug, and a good
demonstration that clamping a step is not the same as clamping a debt.

`requestAnimationFrame` does not run in a hidden tab, so the world stops
advancing while the worker keeps producing simulated time. `SimClock`
capped the per-frame `dt` at 0.1 s — which is what stops one enormous
step integrating the body through a wall — but left the rest of the debt
*owed*. On return it was handed out 0.1 s per frame at sixty frames a
second: **six times realtime, for as long as the tab had been away.**
The doc comment claimed the excess was dropped; the code never dropped
it, and the test only checked a single call, so nothing caught it.

Two fixes. The backlog is now capped as well as the step, so anything
past 0.25 s is discarded rather than replayed — the fly's clock loses
time, which is the right failure: a viewer who looks away misses that
stretch of its life rather than watching it fast-forwarded. And the
worker is paused outright on `visibilitychange`, so the debt does not
accrue in the first place; measured at 0.02 s of simulated time across
eight wall seconds hidden, against 0.40x when visible. That also stops a
backgrounded tab burning a core on a simulation nobody is watching.

### Phase 4, 2026-08-21: the benchmark, and the answer

Code: `web/harness/fff-bench.ts`, `npm run bench` (`--smoke` in CI),
output at `public/brain/bench.json`.

**The fly does not play Flappy Bird.** 60 rounds per arm, one seed, a
320-second capture of the real thing:

| arm | median score | 95% CI | median alive | best |
|---|---|---|---|---|
| fly | 0 | 0–0 | 4.85 s | 1 |
| poisson (rate-matched) | 0 | 0–0 | 4.85 s | 1 |
| nobody | 0 | 0–0 | 4.85 s | 0 |
| **oracle** (positive control) | **3.0** | 2–5.5 | 9.12 s | 28 |

The fly beats its own rate-matched Poisson control in **50%** of matched
rounds — indistinguishable, which is the definition of chance — and
beats doing nothing in 53%. This is exactly the headline the design doc
predicted and asked for, now with a number attached.

**The positive control is the reason that sentence is worth anything.**
Three arms all scoring zero cannot distinguish "the fly is bad at this"
from "nobody could win this", and the game very nearly is the second: a
flapper with a fixed repeat only sets the bird's *equilibrium height* —
sink, hover, or pinned to the ceiling — while the gaps sit where they
sit. An oracle that can see the next gap clears 3 pipes on the same
pipes, so the game is winnable and the fly simply does not win it.
Without that row this measurement would have been unreadable, and it was
not in the plan.

**Capture once, replay many.** The plan asked for ~200 rounds per arm,
which run naively is three separate twenty-minute brain simulations. The
pads do not feed back into the fly — pressing one flaps a bird, and the
bird cannot touch the fly — so one long capture replays through every
round of every arm, the same argument M0.2 made. Hours become minutes.
The approximation it makes is recorded in the harness: the fly *sees*
the game, and the bird's position does depend on the arm, but the bird is
a 26 px sprite on the far side of the canvas and the pipes dominate what
the eyes get.

**The doc's emergent question, answered: yes, and often.** It asked
whether looming pipes fire LC4 and cause accidental pad-saves. Over the
capture the fly startled 53 times and **30 of those startles — 57% —
ended with it on the plate.** More than half of the fly's escapes are
accidental button presses. It is the most game-like thing the fly does,
and it is entirely unintentional.

Measured alongside: the fly presses **117 times per minute** of
simulated time in the chamber, against M0.2's ~4 per minute on the open
960×540 field. That is the chamber and the repeating plate doing their
work, and it is the padstats re-measurement Phase 2 said was owed.

Still open: one seed only. A second would be cheap and is worth doing
before the number goes anywhere public.

### Phase 3 completed + Phase 5, 2026-08-21: the hall, the poke panel, the deploy

**The cabinet hall exists** at `/`: four cabinets, two lit (Fruit Flappy
Fly, and the fly loose on a canvas at `/bench/`) and two dark (Pong,
Tetris) with the design doc's own reasoning on the card. The benchmark's
numbers are on the hub as well as the cabinet, from one shared module so
the two cannot drift into quoting different figures.

**Poke mode ships with the cabinet**, which the design doc insists is
the product rather than a debug affordance — "QWOP with optogenetics".
Seven populations, live mid-round, verified end to end in a browser:
clicking `GF` took the giant fiber from 5.3 Hz to 52.0 Hz and the fly
bolted. Nothing about that is scripted; the button forces one real
population through the same channel the retina uses.

**Phase 5's deploy half is written.** `web/Dockerfile` builds the brain
and the site in separate stages from the repository root (the connectome
comes from the Python half, so the context has to include it) and serves
from `nginx:alpine`. `web/nginx.conf` listens on 8080 with `/ping` — not
`/healthz`, which the Google Front End reserves — and carries the CSP
line the template it borrows from is missing: **`worker-src 'self'
blob:`**, without which the page loads, shows its bar and never starts a
fly, because `default-src` does not cover workers in every engine.
`deploy-web.yml` fires on `web-v*` tags, re-runs the gates, asserts the
tag matches `web/package.json`, enforces a 2 MB gzipped bundle budget on
the non-brain code, deploys `--no-traffic --tag smoke`, curls the
revision — including a size check on `brain.bin`, the failure that would
otherwise only show up in someone's browser — and only then sends
traffic, with a tag rollback on failure and an optional CDN purge that
skips cleanly while the zone does not exist.

Not done here, and deliberately: nothing has been deployed. No GCP
resources were touched, no tag was pushed. The runbook exists and the
first `web-v0.1.0` tag is a human decision.

## Build order

Phase 0 (measurements) → 1 (brain + parity) → 2 (senses/motor/runtime)
→ 3 (fff + API) → 4 (benchmark) → 5 (CI + the fly's own service)
→ ops steps → tag `web-v1.0.0` here → router entry (+ apex redirect
until the vitrine exists) → the Fruit Fly Arcade is live at
fly.rembi.sh and losing. The rembi.sh vitrine follows on its own
schedule.

Each phase lands as its own PR against this repo (or rembi.sh for
Phase 5's site half), keeping the existing checks green throughout —
the desktop fly must never regress while the web fly grows.
