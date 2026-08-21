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
  reopened that door).

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
