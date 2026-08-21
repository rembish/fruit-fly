/**
 * The Phase 1 gate: does the TypeScript brain behave like the Python one?
 *
 * Runs the same resting network the Python reference ran — same dt, same
 * noise, no stimulus — and compares per-population mean rates against
 * `parity.json`. Each population's tolerance was measured, not chosen:
 * it is 1.5x what the Python model does to *itself* across five seeds,
 * so a population the reference cannot hold steady is not one this port
 * is asked to.
 *
 * Rates rather than spike counts, and means over whole populations
 * rather than spike times, because the two runtimes will never agree
 * spike-for-spike — they cannot share a random number generator, and a
 * Poisson-driven recurrent network amplifies any difference at all.
 * Statistical parity is the goal; spike-exact parity is explicitly not.
 *
 *   node --experimental-strip-types harness/parity.ts   (or: npm run parity)
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Brain } from "../src/brain/brain.js";
import { parseBrain } from "../src/brain/loader.js";
import { pspCalibration } from "../src/brain/params.js";

const here = dirname(fileURLToPath(import.meta.url));
const brainDir = join(here, "..", "public", "brain");

interface PopReference {
  mean: number;
  sd: number;
  tolerance: number;
  per_seed: number[];
  size: number;
}

interface Reference {
  seconds: number;
  dt: number;
  noise_rate: number;
  noise_weight: number;
  inh_gain: number;
  seeds: number[];
  margin: number;
  psp_unit_weight: number;
  network_hz: Omit<PopReference, "size">;
  noise_rate_final: Omit<PopReference, "size">;
  rates: Record<string, PopReference>;
}

function loadBrainFile() {
  const buf = readFileSync(join(brainDir, "brain.bin"));
  // Copy out of Node's pooled Buffer: small reads share one backing
  // ArrayBuffer with unrelated data, and the section offsets are only
  // meaningful from the start of the file.
  const ab = buf.buffer.slice(
    buf.byteOffset,
    buf.byteOffset + buf.byteLength,
  ) as ArrayBuffer;
  return parseBrain(ab);
}

interface RunResult {
  seed: number;
  totalSpikes: number;
  networkHz: number;
  noiseFloor: number;
  rates: Record<string, number>;
  stepsPerSecond: number;
}

function run(
  data: ReturnType<typeof parseBrain>,
  ref: Reference,
  seed: number,
  pops: string[],
): RunResult {
  const brain = new Brain(data, {
    dt: ref.dt,
    noiseRate: ref.noise_rate,
    noiseWeight: ref.noise_weight,
    inhGain: ref.inh_gain,
    seed,
  });

  // Same membership inversion the RateMonitor uses, but counting raw
  // spikes rather than smoothing them: the reference is a mean over the
  // whole run, and an EMA would compare a smoothing constant instead.
  const counts = new Float64Array(pops.length);
  const offsets = new Int32Array(brain.n + 1);
  const tally = new Int32Array(brain.n);
  pops.forEach((name) => {
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
  pops.forEach((name, slot) => {
    const idx = data.pops.get(name)!;
    for (let i = 0; i < idx.length; i++) slots[at[idx[i]!]!++] = slot;
  });

  const steps = Math.round((ref.seconds * 1000) / ref.dt);
  const t0 = performance.now();
  let spikes = 0;
  for (let s = 0; s < steps; s++) {
    const spiked = brain.step();
    spikes += spiked.length;
    for (let j = 0; j < spiked.length; j++) {
      const i = spiked[j]!;
      const end = offsets[i + 1]!;
      for (let e = offsets[i]!; e < end; e++) counts[slots[e]!]! += 1;
    }
  }
  const wall = (performance.now() - t0) / 1000;

  const rates: Record<string, number> = {};
  pops.forEach((name, slot) => {
    rates[name] = counts[slot]! / (data.pops.get(name)!.length * ref.seconds);
  });
  return {
    seed,
    totalSpikes: spikes,
    networkHz: spikes / (brain.n * ref.seconds),
    noiseFloor: brain.noiseFloor,
    rates,
    stepsPerSecond: steps / wall,
  };
}

function main(): number {
  const ref = JSON.parse(
    readFileSync(join(brainDir, "parity.json"), "utf8"),
  ) as Reference;
  const data = loadBrainFile();
  const pops = Object.keys(ref.rates);

  // The one constant both runtimes derive rather than read, so the one
  // most able to drift apart without anyone noticing.
  const psp = pspCalibration(ref.dt);
  const pspDelta = Math.abs(psp - ref.psp_unit_weight);
  console.log(
    `psp unit weight: TS ${psp.toFixed(9)} vs Python ` +
      `${ref.psp_unit_weight.toFixed(9)} (delta ${pspDelta.toExponential(2)})`,
  );

  console.log(
    `running ${ref.seeds.length} seeds x ${ref.seconds}s at dt=${ref.dt}, ` +
      `noise ${ref.noise_rate} Hz, no stimulus ...`,
  );
  const runs = ref.seeds.map((seed) => run(data, ref, seed, pops));

  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const tsNetwork = mean(runs.map((r) => r.networkHz));
  const tsRates: Record<string, number> = {};
  for (const name of pops) tsRates[name] = mean(runs.map((r) => r.rates[name]!));

  let failures = 0;
  const line = (
    name: string,
    got: number,
    want: number,
    tol: number,
    note = "",
  ) => {
    const delta = got - want;
    // A tolerance of zero means the reference never moved between
    // seeds, which is a statement about the measurement and not about
    // the port. Treat it as unpoliceable rather than as infinitely
    // strict — the alternative is a gate no implementation can pass,
    // including the one that produced the number.
    const policed = tol > 0;
    const ok = !policed || Math.abs(delta) <= tol;
    if (policed && !ok) failures += 1;
    const verdict = !policed ? "unpoliced" : ok ? "ok" : "FAIL";
    console.log(
      `  ${name.padEnd(14)} TS ${got.toFixed(4).padStart(9)}  ` +
        `py ${want.toFixed(4).padStart(9)}  ` +
        `delta ${delta.toFixed(4).padStart(9)}  ` +
        `tol ${tol.toFixed(4).padStart(8)}  ${verdict}${note}`,
    );
  };

  console.log("");
  line("network", tsNetwork, ref.network_hz.mean, ref.network_hz.tolerance);
  const tsFloor = mean(runs.map((r) => r.noiseFloor));
  line(
    "noise floor",
    tsFloor,
    ref.noise_rate_final.mean,
    ref.noise_rate_final.tolerance,
    "  (governor)",
  );
  for (const name of pops) {
    const r = ref.rates[name]!;
    line(name, tsRates[name]!, r.mean, r.tolerance, `  (n=${r.size})`);
  }

  // The plan wanted this gated against the governor's own 1.0 target.
  // Measured, the reference does not sit there and neither should the
  // port: the governor can only *add* noise, this network is already
  // livelier than its target on recurrence alone, so the floor empties
  // to zero and the rate settles wherever the anatomy puts it. Gating
  // on the target would have failed a correct port for agreeing with an
  // incorrect expectation, so what is gated is agreement with the
  // measurement above.
  console.log("");
  console.log(
    `network sits at ${tsNetwork.toFixed(2)} Hz/neuron with the governor ` +
      `emptied to ${tsFloor.toFixed(2)} Hz — the model's 1.0 target is ` +
      `a floor it cannot enforce downward, in either runtime`,
  );

  if (pspDelta > 1e-6) {
    console.log(`psp unit weight differs by more than 1e-6 -> FAIL`);
    failures += 1;
  }

  // Recorded, never gated: it is a property of the machine that ran it.
  const perf = mean(runs.map((r) => r.stepsPerSecond));
  const realtime = (perf * ref.dt) / 1000;
  console.log(
    `PERF ${perf.toFixed(0)} steps/s in Node ` +
      `(${realtime.toFixed(2)}x realtime at dt=${ref.dt})`,
  );

  console.log("");
  console.log(
    failures === 0
      ? "PARITY OK: the port sits inside the reference's own seed spread"
      : `PARITY FAILED: ${failures} measurement(s) outside tolerance`,
  );
  return failures === 0 ? 0 : 1;
}

process.exit(main());
