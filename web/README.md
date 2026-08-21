# The fly, in a browser

The same connectome, the same LIF model, the same tuned motor map — in
TypeScript, held to the Python original by a parity gate that measures
rather than assumes.

## Running it

The brain is not in git. It is 17 MB, it is a build artefact, and it is
CC BY-NC data besides, so you compile it from the connectome first:

```bash
# from the repository root, once (downloads ~50 MB the first time)
python -m fruitfly export-web --no-parity   # -> web/public/brain/brain.bin

# then, in web/
npm ci
npm run dev                                  # http://localhost:5173/
```

Drop `--no-parity` to also measure the reference the gate compares
against; that takes about five minutes and is only needed if you intend
to run `npm run parity`.

## What you get

A fly on a 960×540 canvas, its body driven by 139,255 neurons running in
a worker. Move the pointer over the canvas and it will see you — the
cursor is drawn into the retina with the angular size a flat screen
cannot supply, so an approach genuinely looms. Click on the fly to swat
it: on the ground it squashes, airborne it is a glancing blow. The
buttons drive one real population directly, and nothing about the
reaction is scripted.

**`sim` under 1.00× is the design, not a bug.** The brain free-runs and
the whole world takes its pace from the simulated time it produces, so a
slow machine shows the fly in honest slow motion with every tuned
constant still meaning what it meant. The alternative — advancing the
world by the wall clock while the brain lags — silently rescales every
threshold in the motor map, and the failure looks like a fly that will
not land rather than like a clock bug.

## Checks

```bash
npm run typecheck     # tsc --noEmit
npm test              # vitest, colocated *.test.ts
npm run parity        # TS brain vs the Python reference, 5 seeds x 60 bio-s
npm run sense-parity  # ... and again with the eyes open on a flat field
npm run smoke         # drives the real page in a headless browser
```

`parity` and `sense-parity` need `brain.bin`; `smoke` needs it *and* a
dev server already running. The first two are the ones that would catch
a port that quietly became a different model; `smoke` is the one that
catches a page that type-checks perfectly and shows nothing, which is a
different failure and not a rarer one.

## Layout

```
src/brain/     brain.ts, params.ts, rng.ts, loader.ts — DOM-free
src/senses/    retina.ts, senses.ts
src/motor/     motor.ts (the tuned map), pads.ts (the press rule)
src/runtime/   worker.ts, protocol.ts, controller.ts, simclock.ts
src/ui/        the fly, drawn
src/pages/     one entry per page
harness/       Node: parity, sense-parity, smoke
public/brain/  brain.bin + meta.json (gitignored build artefact)
```
