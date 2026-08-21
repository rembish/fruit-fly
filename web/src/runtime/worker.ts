/// <reference lib="webworker" />
/**
 * The brain thread: sense, step, report. Nothing else lives here.
 *
 * The scheduling is the part worth reading. A worker that steps the brain
 * in a tight `while` loop never returns to its own event loop, so it
 * never receives a `sense` message — the fly goes blind and the symptom
 * looks like a retina bug rather than a scheduling one. So each pass runs
 * one short chunk of simulated time and then yields with `setTimeout`,
 * which lets queued messages land. A microtask would not: promises are
 * drained before message events, so a `Promise.resolve()` loop starves
 * the queue just as thoroughly as a `while`.
 *
 * This file also holds the **only** legitimate comparison of simulated
 * time against wall time in the whole runtime: the cap that stops a fast
 * machine from running the fly at 3x. Everything downstream takes its
 * pace from `simTimeMs` and never looks at a clock.
 */

import { Brain, RateMonitor } from "../brain/brain.js";
import { parseBrain, type BrainData } from "../brain/loader.js";
import { Retina, retinaFromSections } from "../senses/retina.js";
import { Senses, type SensoryFrame } from "../senses/senses.js";
import type { FromWorker, ToWorker } from "./protocol.js";

/** What the motor map reads, plus the loom detectors for the HUD. */
const MOTOR_POPS = [
  "GF",
  "DNa02_L",
  "DNa02_R",
  "DNp09",
  "MDN",
  "descending",
  "LC4_L",
  "LC4_R",
];

/**
 * Simulated ms per scheduling pass. ~16 ms is one display frame's worth,
 * so the main thread gets a fresh tick about once per repaint when the
 * machine can keep up, and simply gets fewer when it cannot.
 */
const CHUNK_MS = 16;

const ctx = self as unknown as DedicatedWorkerGlobalScope;
const post = (m: FromWorker, transfer: Transferable[] = []) =>
  ctx.postMessage(m, transfer);

let brain: Brain | null = null;
let monitor: RateMonitor | null = null;
let senses: Senses | null = null;
/** Neuron -> is it a giant fiber, built once at load. */
let gfMark: Uint8Array = new Uint8Array(0);
let running = true;

const frame: SensoryFrame = {
  cursorX: 1e9,
  cursorY: 1e9,
  patchL: null,
  patchR: null,
  patchDt: 0.05,
};
let flyX = 480;
let flyY = 270;
let heading = 0;

/** A poke holds until this simulated time, in ms. */
let poke: { pop: string; hz: number; untilMs: number } | null = null;

let gfCount = 0;
let lastReportSim = 0;
let lastReportWall = 0;
let spikesWindow = 0;
let simSpeed = 0;
let spikesPerSecond = 0;

async function load(url: string, opts: {
  seed: number;
  noiseRate: number;
  noiseWeight: number;
  inhGain: number;
  dt: number;
  loomInjection: number;
}): Promise<void> {
  post({ kind: "progress", loaded: null, note: "downloading the brain" });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`brain.bin: HTTP ${res.status}`);

  // Stream it so the loading bar means something: 17 MB is long enough
  // on a slow connection that a frozen page would look broken.
  const total = Number(res.headers.get("content-length") ?? 0);
  let buf: ArrayBuffer;
  if (res.body && total > 0) {
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      post({ kind: "progress", loaded: got / total, note: "downloading the brain" });
    }
    const all = new Uint8Array(got);
    let at = 0;
    for (const c of chunks) {
      all.set(c, at);
      at += c.length;
    }
    buf = all.buffer;
  } else {
    buf = await res.arrayBuffer();
  }

  post({ kind: "progress", loaded: 1, note: "wiring 2.7 M connections" });
  const data: BrainData = parseBrain(buf);
  brain = new Brain(data, {
    dt: opts.dt,
    noiseRate: opts.noiseRate,
    noiseWeight: opts.noiseWeight,
    inhGain: opts.inhGain,
    seed: opts.seed,
  });
  monitor = new RateMonitor(brain, MOTOR_POPS);
  const gf = data.pops.get("GF") ?? new Int32Array(0);
  gfMark = new Uint8Array(brain.n);
  for (let i = 0; i < gf.length; i++) gfMark[gf[i]!] = 1;
  senses = new Senses(new Retina(retinaFromSections(data.retina)), {
    loomInjection: opts.loomInjection,
  });

  post({
    kind: "ready",
    neurons: data.header.n_neurons,
    connections: data.header.n_connections,
    attribution: data.header.attribution,
    pops: [...data.pops.keys()].sort(),
  });
  lastReportWall = performance.now();
  lastReportSim = brain.t;
  schedule();
}

function schedule(): void {
  setTimeout(pass, 0);
}

function pass(): void {
  const b = brain;
  const mon = monitor;
  const sn = senses;
  if (!b || !mon || !sn) return;
  if (!running) {
    schedule();
    return;
  }

  const wall0 = performance.now();
  const simTarget = b.t + CHUNK_MS;

  // Sense once per chunk, at the position the main thread last reported.
  const world = sn.sense(frame, flyX, flyY, heading, b.t / 1000);
  const stim: Parameters<Brain["setStimulus"]>[0] = [
    ...world.channels.map((c) => ({ idx: c.idx, rate: c.rate })),
    ...world.pops,
  ];
  if (poke) {
    if (b.t < poke.untilMs) stim.push({ pop: poke.pop, rate: poke.hz });
    else poke = null;
  }
  b.setStimulus(stim);

  while (b.t < simTarget) {
    const spiked = b.step();
    mon.update(spiked);
    spikesWindow += spiked.length;
    for (let j = 0; j < spiked.length; j++) {
      if (gfMark[spiked[j]!]) gfCount += 1;
    }
  }

  const wall1 = performance.now();
  if (wall1 - lastReportWall >= 500) {
    const dtWall = (wall1 - lastReportWall) / 1000;
    simSpeed = (b.t - lastReportSim) / 1000 / dtWall;
    spikesPerSecond = spikesWindow / dtWall;
    lastReportWall = wall1;
    lastReportSim = b.t;
    spikesWindow = 0;
  }

  post({
    kind: "tick",
    simTimeMs: b.t,
    rates: mon.snapshot(),
    gfCount,
    threat: world.threat,
    bearing: world.bearing,
    simSpeed,
    spikesPerSecond,
  });
  gfCount = 0;

  // The one place simulated time is compared to wall time: hold the fly
  // to at most 1x so a fast machine does not run it in fast-forward.
  // Everything downstream takes its pace from simTimeMs alone.
  const spent = performance.now() - wall0;
  const delay = Math.max(0, CHUNK_MS - spent);
  setTimeout(pass, delay);
}

ctx.onmessage = (ev: MessageEvent<ToWorker>) => {
  const msg = ev.data;
  switch (msg.kind) {
    case "start":
      load(msg.brainUrl, msg).catch((e: unknown) => {
        post({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      });
      break;
    case "sense":
      frame.patchL = msg.patchL;
      frame.patchR = msg.patchR;
      frame.patchDt = msg.patchDt;
      frame.cursorX = msg.cursorX;
      frame.cursorY = msg.cursorY;
      flyX = msg.flyX;
      flyY = msg.flyY;
      heading = msg.heading;
      break;
    case "poke":
      if (brain) {
        poke = { pop: msg.pop, hz: msg.hz, untilMs: brain.t + msg.seconds * 1000 };
      }
      break;
    case "control":
      if (msg.reset && brain) brain.resetState();
      if (msg.running !== undefined) running = msg.running;
      break;
  }
};
