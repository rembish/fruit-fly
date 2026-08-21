/**
 * The Phase 1 gate with the eyes open.
 *
 * Phase 1 proved the brain alone matches Python. That gate runs with no
 * stimulus at all, so it cannot see a fault in the retina, the column
 * mapping, or the way per-neuron rates are handed to `setStimulus` — and
 * those are half of what Phase 2 added. A brain that idles correctly and
 * then mis-drives six thousand photoreceptors is a brain that looks
 * right in CI and wrong on the page.
 *
 * So: hold both eyes at a fixed luminance, let adaptation settle, and
 * compare the same populations the brain gate compares. A flat field is
 * the point — it is the one stimulus whose Python answer can be computed
 * without also porting a scene.
 *
 *   npm run sense-parity      (needs brain.bin)
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Brain, RateMonitor } from "../src/brain/brain.js";
import { parseBrain } from "../src/brain/loader.js";
import { PATCH, Retina, retinaFromSections } from "../src/senses/retina.js";
import { Senses, type SensoryFrame } from "../src/senses/senses.js";

const here = dirname(fileURLToPath(import.meta.url));
const brainDir = join(here, "..", "public", "brain");

/** Sensory frames per second, as the desktop drives them. */
const TICK = 0.05;
const WARM_S = 5.0;
const MEASURE_S = 20.0;

const POPS = ["descending", "GF", "DNa02_L", "DNa02_R"];

/**
 * What `fruitfly` produces for the same stimulus, measured on this
 * machine with seed 7. Two luminances: the dark scene the bench page
 * renders, and the mid gray M0.3 used.
 */
const REFERENCE: Record<string, Record<string, number>> = {
  "0.13": { descending: 5.84, GF: 3.2, DNa02_L: 26.5, DNa02_R: 17.65 },
  "0.55": { descending: 5.63, GF: 3.45, DNa02_L: 23.95, DNa02_R: 18.0 },
};

/**
 * Generous, and deliberately so. This is a single seed on both sides and
 * the Phase 1 gate measured seed-to-seed spread of 0.55 Hz on a
 * one-neuron population; what this catches is a port that is wrong by a
 * factor, not one that is wrong in the last decimal.
 */
const TOLERANCE_FRACTION = 0.25;

function loadBrainFile() {
  const buf = readFileSync(join(brainDir, "brain.bin"));
  const ab = buf.buffer.slice(
    buf.byteOffset,
    buf.byteOffset + buf.byteLength,
  ) as ArrayBuffer;
  return parseBrain(ab);
}

function run(lum: number): Record<string, number> {
  const data = loadBrainFile();
  const brain = new Brain(data, {
    dt: 2.0,
    noiseRate: 100,
    noiseWeight: 3,
    inhGain: 1.5,
    seed: 7,
  });
  const mon = new RateMonitor(brain, POPS);
  const senses = new Senses(new Retina(retinaFromSections(data.retina)), {
    loomInjection: 0.4,
  });

  const patch = new Float32Array(PATCH * PATCH).fill(lum);
  const frame: SensoryFrame = {
    cursorX: 1e9,
    cursorY: 1e9,
    patchL: patch,
    patchR: patch,
    patchDt: TICK,
  };

  const counts = new Float64Array(POPS.length);
  const offsets = new Int32Array(brain.n + 1);
  const tally = new Int32Array(brain.n);
  POPS.forEach((name) => {
    const idx = data.pops.get(name)!;
    for (let i = 0; i < idx.length; i++) tally[idx[i]!]! += 1;
  });
  let total = 0;
  for (let i = 0; i < brain.n; i++) {
    offsets[i] = total;
    total += tally[i]!;
  }
  offsets[brain.n] = total;
  const slots = new Int32Array(total);
  const at = offsets.slice(0, brain.n);
  POPS.forEach((name, slot) => {
    const idx = data.pops.get(name)!;
    for (let i = 0; i < idx.length; i++) slots[at[idx[i]!]!++] = slot;
  });

  const stepsPerTick = Math.round((TICK * 1000) / 2.0);
  const warm = Math.round(WARM_S / TICK);
  const ticks = Math.round(MEASURE_S / TICK);
  for (let i = 0; i < warm + ticks; i++) {
    const world = senses.sense(frame, 500, 500, 0, brain.t / 1000);
    brain.setStimulus([
      ...world.channels.map((c) => ({ idx: c.idx, rate: c.rate })),
      ...world.pops,
    ]);
    for (let s = 0; s < stepsPerTick; s++) {
      const spiked = brain.step();
      mon.update(spiked);
      if (i >= warm) {
        for (let j = 0; j < spiked.length; j++) {
          const n = spiked[j]!;
          const end = offsets[n + 1]!;
          for (let e = offsets[n]!; e < end; e++) counts[slots[e]!]! += 1;
        }
      }
    }
  }

  const out: Record<string, number> = {};
  POPS.forEach((name, slot) => {
    out[name] = counts[slot]! / (data.pops.get(name)!.length * MEASURE_S);
  });
  return out;
}

function main(): number {
  let failures = 0;
  for (const [key, want] of Object.entries(REFERENCE)) {
    const lum = Number(key);
    console.log(`\nboth eyes held at ${lum} luminance, ${MEASURE_S}s measured:`);
    const got = run(lum);
    for (const name of POPS) {
      const w = want[name]!;
      const g = got[name]!;
      const tol = Math.max(0.5, Math.abs(w) * TOLERANCE_FRACTION);
      const ok = Math.abs(g - w) <= tol;
      if (!ok) failures += 1;
      console.log(
        `  ${ok ? "ok  " : "FAIL"}  ${name.padEnd(10)} TS ${g.toFixed(2).padStart(7)}` +
          `  py ${w.toFixed(2).padStart(7)}  tol ${tol.toFixed(2)}`,
      );
    }
  }
  console.log("");
  console.log(
    failures === 0
      ? "SENSE PARITY OK: the eyes drive the brain the way Python's do"
      : `SENSE PARITY FAILED: ${failures} population(s) off`,
  );
  return failures === 0 ? 0 : 1;
}

process.exit(main());
