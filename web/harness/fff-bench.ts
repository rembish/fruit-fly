/**
 * The benchmark: does the fly beat chance at Flappy Bird?
 *
 * This is the half of the project that is a measurement rather than a
 * toy, and the design doc is explicit about the register: the headline
 * is not "a fly plays Flappy Bird" — that reads as brain-computer-
 * interface hype — but "a fruit fly's connectome scores no better than
 * chance at Flappy Bird, and here is the number". Three arms:
 *
 *   fly       the real thing: 139,255 neurons, real eyes, real body
 *   poisson   a coin weighted to the fly's *own* measured press rate
 *   nobody    nothing presses anything
 *
 * If the fly beats nobody, that is interesting. If it does not beat
 * poisson, that is the honest headline and a better one than any score.
 *
 * ## Capture once, replay many
 *
 * The plan asked for ~200 rounds per arm. Run naively that is three
 * separate brain simulations of about twenty minutes each, because the
 * brain costs ~0.4x realtime and nothing else here costs anything.
 *
 * It does not need to be. **The pads do not feed back into the fly**:
 * pressing one flaps a bird, and the bird cannot touch the fly. So the
 * fly's press train is a property of the fly alone, and one long
 * capture can be replayed through as many rounds and as many arms as we
 * like — which is exactly the technique M0.2 used on the same grounds,
 * and it turns hours into a couple of minutes.
 *
 * The one approximation this makes: the fly *sees* the game, and in
 * controller mode the bird's position depends on the arm. The bird is a
 * 26 px sprite on the far side of the canvas from the chamber, and the
 * pipes — which dominate the scene and are identical across arms at a
 * given seed — are what the fly's eyes actually get. It is recorded here
 * rather than hidden.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createCanvas } from "@napi-rs/canvas";

import { Brain, RateMonitor } from "../src/brain/brain.js";
import { parseBrain } from "../src/brain/loader.js";
import { Retina, retinaFromSections, EYE_RADIUS, PATCH } from "../src/senses/retina.js";
import { Senses, type SensoryFrame } from "../src/senses/senses.js";
import { MotorMap, ESCAPE, TAKEOFF } from "../src/motor/motor.js";
import { PressDetector, onPad } from "../src/motor/pads.js";
import { Fff, FLY_BOX, BOX_PAD, PLATE_REPEAT_S } from "../src/games/fff/fff.js";
import { CANVAS_W, CANVAS_H } from "../src/runtime/controller.js";

const here = dirname(fileURLToPath(import.meta.url));
const brainDir = join(here, "..", "public", "brain");
const outDir = join(here, "..", "public", "brain");

const DT_SIM = 1 / 60; // the frame the runtime drives the body at
const SENSE_HZ = 20;
const BRAIN_DT = 2.0;
const CHUNK_MS = 16;

const args = new Map<string, string>();
for (const a of process.argv.slice(2)) {
  const m = /^--([^=]+)(?:=(.*))?$/.exec(a);
  if (m) args.set(m[1]!, m[2] ?? "1");
}
const num = (k: string, d: number) => Number(args.get(k) ?? d);

/** Simulated seconds of fly to capture. Each round eats ~5 of them. */
const CAPTURE_S = num("capture", 320);
const ROUNDS = num("rounds", 60);
const SEED = num("seed", 7);
const SMOKE = args.has("smoke");

interface Capture {
  seconds: number;
  /** Simulated times of every plate press, in seconds. */
  presses: number[];
  /** Presses per minute of simulated time. */
  pressRate: number;
  /** Escapes that ended with the fly on the plate: accidental saves. */
  escapesOntoPlate: number;
  escapes: number;
  meanLc4: number;
  meanDescending: number;
  simSpeed: number;
}

function loadBrainFile() {
  const buf = readFileSync(join(brainDir, "brain.bin"));
  const ab = buf.buffer.slice(
    buf.byteOffset,
    buf.byteOffset + buf.byteLength,
  ) as ArrayBuffer;
  return parseBrain(ab);
}

/**
 * Run the real fly for a while and write down when it pressed.
 *
 * The scene is rendered with a headless canvas rather than a
 * reimplementation, so the pixels the fly's retina sees here are the
 * pixels the page would give it. A second renderer would be a second
 * thing that could disagree.
 */
function capture(seconds: number): Capture {
  const data = loadBrainFile();
  const brain = new Brain(data, {
    dt: BRAIN_DT,
    noiseRate: 100,
    noiseWeight: 3,
    inhGain: 1.5,
    seed: SEED,
  });
  const mon = new RateMonitor(brain, [
    "GF",
    "DNa02_L",
    "DNa02_R",
    "DNp09",
    "MDN",
    "descending",
    "LC4_L",
    "LC4_R",
  ]);
  const gf = data.pops.get("GF")!;
  const gfMark = new Uint8Array(brain.n);
  for (let i = 0; i < gf.length; i++) gfMark[gf[i]!] = 1;

  const senses = new Senses(new Retina(retinaFromSections(data.retina)), {
    loomInjection: 0.4,
  });
  const motor = new MotorMap(CANVAS_W, CANVAS_H);
  motor.bounds = {
    x0: FLY_BOX[0] * CANVAS_W,
    y0: FLY_BOX[1] * CANVAS_H,
    x1: FLY_BOX[2] * CANVAS_W,
    y1: FLY_BOX[3] * CANVAS_H,
  };

  // A live game, purely so the fly has the right thing to look at. Its
  // score is thrown away; the arms are scored in the replay.
  const scenery = new Fff({ width: CANVAS_W, height: CANVAS_H, seed: SEED });
  const world = createCanvas(CANVAS_W, CANVAS_H);
  const wctx = world.getContext("2d");

  const presses = new PressDetector();
  const frame: SensoryFrame = {
    cursorX: -1e9,
    cursorY: -1e9,
    patchL: null,
    patchR: null,
    patchDt: 1 / SENSE_HZ,
    // no cursor: nobody is sabotaging a benchmark
  };

  const pressTimes: number[] = [];
  let escapes = 0;
  let escapesOntoPlate = 0;
  let wasEscaping = false;
  let lc4Sum = 0;
  let descSum = 0;
  let samples = 0;
  let nextSenseAt = 0;
  let lastSenseAt = 0;
  let gfCount = 0;

  const wall0 = Date.now();
  const frames = Math.round(seconds / DT_SIM);
  const stepsPerChunk = Math.round(CHUNK_MS / BRAIN_DT);

  for (let f = 0; f < frames; f++) {
    const t = f * DT_SIM;

    // The brain runs a chunk per frame; the worker paces it the same way.
    const s = senses.sense(frame, motor.st.x, motor.st.y, motor.st.heading, t);
    brain.setStimulus([
      ...s.channels.map((c) => ({ idx: c.idx, rate: c.rate })),
      ...s.pops,
    ]);
    for (let i = 0; i < stepsPerChunk; i++) {
      const spiked = brain.step();
      mon.update(spiked);
      for (let j = 0; j < spiked.length; j++) if (gfMark[spiked[j]!]) gfCount += 1;
    }

    motor.update(DT_SIM, t, mon.snapshot(), gfCount, s.bearing, s.threat);
    gfCount = 0;

    // The doc's emergent question: does a startle ever end with the fly
    // on the plate — a save it did not mean to make?
    const escaping = motor.st.state === ESCAPE || motor.st.state === TAKEOFF;
    if (escaping && !wasEscaping) escapes += 1;
    if (wasEscaping && !escaping) {
      if (onPad(BOX_PAD, motor.st, CANVAS_W, CANVAS_H)) escapesOntoPlate += 1;
    }
    wasEscaping = escaping;

    for (const _p of presses.poll(
      scenery.pads(),
      motor.st,
      CANVAS_W,
      CANVAS_H,
      "passing",
      DT_SIM,
      PLATE_REPEAT_S,
    )) {
      pressTimes.push(t);
    }

    // Keep the scenery moving so the eyes have a real scene, and redraw
    // it for the retina.
    scenery.tick({ dt: DT_SIM, t, fly: motor.st, pressed: [] });
    scenery.drawWorld(wctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H);

    if (t >= nextSenseAt) {
      nextSenseAt = t + 1 / SENSE_HZ;
      frame.patchDt = Math.min(0.5, t - lastSenseAt);
      lastSenseAt = t;
      frame.patchL = samplePatch(wctx, motor.st, "L");
      frame.patchR = samplePatch(wctx, motor.st, "R");
    }

    const r = mon.snapshot();
    lc4Sum += ((r["LC4_L"] ?? 0) + (r["LC4_R"] ?? 0)) / 2;
    descSum += r["descending"] ?? 0;
    samples += 1;

    if (f % 1200 === 0) {
      process.stdout.write(
        `\r  captured ${(t).toFixed(0)}/${seconds}s of fly ` +
          `(${pressTimes.length} presses)   `,
      );
    }
  }
  process.stdout.write("\n");

  return {
    seconds,
    presses: pressTimes,
    pressRate: (pressTimes.length / seconds) * 60,
    escapesOntoPlate,
    escapes,
    meanLc4: lc4Sum / samples,
    meanDescending: descSum / samples,
    simSpeed: seconds / ((Date.now() - wall0) / 1000),
  };
}

type Ctx2D = ReturnType<ReturnType<typeof createCanvas>["getContext"]>;

function samplePatch(
  wctx: Ctx2D,
  st: { x: number; y: number; heading: number },
  eye: "L" | "R",
): Float32Array {
  const [cx, cy] = Senses.eyeCentre(st.x, st.y, st.heading, eye);
  const side = Math.round(2 * EYE_RADIUS);
  const sx = Math.max(0, Math.min(CANVAS_W - side, Math.round(cx - EYE_RADIUS)));
  const sy = Math.max(0, Math.min(CANVAS_H - side, Math.round(cy - EYE_RADIUS)));
  const img = wctx.getImageData(sx, sy, side, side);
  const out = new Float32Array(PATCH * PATCH);
  const step = side / PATCH;
  for (let py = 0; py < PATCH; py++) {
    const srcY = Math.min(side - 1, Math.floor(py * step));
    for (let px = 0; px < PATCH; px++) {
      const srcX = Math.min(side - 1, Math.floor(px * step));
      const o = (srcY * side + srcX) * 4;
      out[py * PATCH + px] =
        (0.299 * img.data[o]! + 0.587 * img.data[o + 1]! + 0.114 * img.data[o + 2]!) /
        255;
    }
  }
  return out;
}

/**
 * Pipe layout for one round.
 *
 * Multiplied rather than offset, and the difference is not cosmetic: at
 * `seed + r` a run at seed 7 and a run at seed 11 shared 56 of their 60
 * pipe layouts, so a "second seed" replicated 93% of the same game and
 * the two agreed for reasons that had nothing to do with the fly. The
 * prime spreads the runs apart so a replication is one.
 */
function roundSeed(seed: number, round: number): number {
  return seed * 7919 + round;
}

interface Round {
  score: number;
  survived: number;
  flaps: number;
}

/**
 * Replay a press train through the game.
 *
 * `pressAt` is asked, for each frame, whether a flap happens. That is
 * the entire interface between an arm and the game, which is what keeps
 * the three comparable: they differ in when the button is pushed and in
 * nothing else.
 */
function replay(
  rounds: number,
  seed: number,
  pressAt: (t: number, dt: number) => number,
): Round[] {
  const out: Round[] = [];
  let t = 0;
  for (let r = 0; r < rounds; r++) {
    const game = new Fff({
      width: CANVAS_W,
      height: CANVAS_H,
      flapper: "fly", // presses come from `pressAt`; the arm decides those
      seed: roundSeed(seed, r),
    });
    let flaps = 0;
    // Rounds cannot run forever: a bird that never dies would hang the
    // benchmark rather than score infinitely.
    const limit = Math.round(120 / DT_SIM);
    for (let f = 0; f < limit && !game.over; f++) {
      t += DT_SIM;
      const n = pressAt(t, DT_SIM);
      flaps += n;
      const pressed = n > 0 ? [BOX_PAD] : [];
      // More than one press in a frame still flaps once: the bird has
      // one pair of wings, and counting them twice would flatter a
      // bursty arm over a steady one.
      game.tick({ dt: DT_SIM, t, fly: FAKE_FLY, pressed });
    }
    out.push({ score: game.score, survived: game.survived, flaps });
  }
  return out;
}

/**
 * The positive control: flap when the bird is below the next gap.
 *
 * Deliberately crude — it is not meant to be good, only to be *possible*.
 * It reads the game's own state, which no arm under test may do, and
 * exists solely to answer "is there any press train that scores here".
 */
function replayOracle(rounds: number, seed: number): Round[] {
  const out: Round[] = [];
  let t = 0;
  for (let r = 0; r < rounds; r++) {
    const game = new Fff({
      width: CANVAS_W,
      height: CANVAS_H,
      flapper: "fly",
      seed: roundSeed(seed, r),
    });
    let flaps = 0;
    const limit = Math.round(120 / DT_SIM);
    for (let f = 0; f < limit && !game.over; f++) {
      t += DT_SIM;
      const target = game.nextGapY;
      const press = game.birdHeight > target;
      if (press) flaps += 1;
      game.tick({
        dt: DT_SIM,
        t,
        fly: FAKE_FLY,
        pressed: press ? [BOX_PAD] : [],
      });
    }
    out.push({ score: game.score, survived: game.survived, flaps });
  }
  return out;
}

/** The replay does not need a fly: the press train already is one. */
const FAKE_FLY = {
  x: 0,
  y: 0,
  heading: 0,
  speed: 0,
  state: "flying" as const,
  wingPhase: 0,
  lastEvent: "",
};

function median(xs: number[]): number {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/**
 * Bootstrap confidence interval for the median.
 *
 * Bootstrapped rather than assumed, because round scores are small
 * integers with a hard floor at zero — nothing about them is normal, and
 * a textbook interval would quietly invent a distribution they do not
 * have.
 */
function medianCI(xs: number[], n = 2000, seed = 1): [number, number] {
  if (xs.length < 2) return [NaN, NaN];
  let s = seed >>> 0;
  const rand = () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
  const meds: number[] = [];
  const draw = new Array<number>(xs.length);
  for (let b = 0; b < n; b++) {
    for (let i = 0; i < xs.length; i++) draw[i] = xs[(rand() * xs.length) | 0]!;
    meds.push(median(draw));
  }
  meds.sort((a, b) => a - b);
  return [meds[Math.floor(n * 0.025)]!, meds[Math.floor(n * 0.975)]!];
}

/** Fraction of pairs where a beats b — a rank comparison, not a t-test. */
function beats(a: number[], b: number[]): number {
  let wins = 0;
  let ties = 0;
  for (const x of a) for (const y of b) {
    if (x > y) wins += 1;
    else if (x === y) ties += 1;
  }
  return (wins + ties / 2) / (a.length * b.length);
}

function main(): number {
  const captureSeconds = SMOKE ? 40 : CAPTURE_S;
  const rounds = SMOKE ? 8 : ROUNDS;

  console.log(
    `Fruit Flappy Fly benchmark — capturing ${captureSeconds}s of fly, ` +
      `then ${rounds} rounds per arm\n`,
  );
  const cap = capture(captureSeconds);
  console.log(
    `  fly pressed ${cap.presses.length} times in ${cap.seconds}s ` +
      `-> ${cap.pressRate.toFixed(1)} per minute of simulated time`,
  );
  console.log(
    `  descending ${cap.meanDescending.toFixed(2)} Hz, LC4 ${cap.meanLc4.toFixed(2)} Hz, ` +
      `captured at ${cap.simSpeed.toFixed(2)}x realtime`,
  );
  console.log(
    `  startles: ${cap.escapes}, of which ${cap.escapesOntoPlate} ended on the plate ` +
      `(${cap.escapes ? ((cap.escapesOntoPlate / cap.escapes) * 100).toFixed(0) : "0"}% — the doc's accidental saves)\n`,
  );

  // The fly arm replays its own presses, looping the capture if the
  // rounds outlast it.
  let cursor = 0;
  const flyPresses = cap.presses;
  const flyArm = replay(rounds, SEED, (t, dt) => {
    let n = 0;
    while (cursor < flyPresses.length && flyPresses[cursor]! <= t % cap.seconds) {
      cursor += 1;
      n += 1;
    }
    if (t % cap.seconds < dt) cursor = 0; // wrapped
    return n;
  });

  // Poisson at the fly's own measured rate: the same amount of button,
  // with none of the fly's timing.
  let ps = 0xbeef;
  const prand = () => {
    ps ^= ps << 13;
    ps ^= ps >>> 17;
    ps ^= ps << 5;
    ps >>>= 0;
    return ps / 4294967296;
  };
  const perSecond = cap.pressRate / 60;
  const poissonArm = replay(rounds, SEED, (_t, dt) =>
    prand() < perSecond * dt ? 1 : 0,
  );
  const nobodyArm = replay(rounds, SEED, () => 0);

  // A positive control, and the benchmark is worthless without one.
  // Three arms that all score zero cannot tell you whether the fly is
  // bad at the game or the game is unwinnable — and this one very nearly
  // is: a flapper with a fixed repeat only sets the bird's *equilibrium
  // height* (sink, hover, or pinned to the ceiling), while the gaps sit
  // wherever they sit. If the oracle cannot score either, the number to
  // fix is the game's, not the fly's, and nothing else here means
  // anything.
  const oracleArm = replayOracle(rounds, SEED);

  const arms: [string, Round[]][] = [
    ["fly", flyArm],
    ["poisson", poissonArm],
    ["nobody", nobodyArm],
    ["oracle", oracleArm],
  ];

  console.log(
    `  ${"arm".padEnd(9)}${"median score".padStart(14)}${"95% CI".padStart(12)}` +
      `${"median alive".padStart(14)}${"best".padStart(6)}`,
  );
  const summary: Record<string, unknown> = {};
  for (const [name, rs] of arms) {
    const scores = rs.map((r) => r.score);
    const alive = rs.map((r) => r.survived);
    const ci = medianCI(scores);
    console.log(
      `  ${name.padEnd(9)}${median(scores).toFixed(1).padStart(14)}` +
        `${`${ci[0]}-${ci[1]}`.padStart(12)}` +
        `${median(alive).toFixed(2).padStart(13)}s` +
        `${Math.max(...scores).toString().padStart(6)}`,
    );
    summary[name] = {
      medianScore: median(scores),
      scoreCI: ci,
      medianAlive: median(alive),
      best: Math.max(...scores),
      rounds: rs.length,
    };
  }

  const flyScores = flyArm.map((r) => r.score);
  const poiScores = poissonArm.map((r) => r.score);
  const nobScores = nobodyArm.map((r) => r.score);
  const vsPoisson = beats(flyScores, poiScores);
  const vsNobody = beats(flyScores, nobScores);
  console.log("");
  console.log(
    `  fly beats poisson in ${(vsPoisson * 100).toFixed(0)}% of matched rounds ` +
      `(50% = indistinguishable)`,
  );
  console.log(
    `  fly beats nobody  in ${(vsNobody * 100).toFixed(0)}% of matched rounds`,
  );
  console.log("");
  const oracleMedian = median(oracleArm.map((r) => r.score));
  console.log(verdict(vsPoisson, vsNobody, median(flyScores), oracleMedian));

  const report = {
    generatedBy: "web/harness/fff-bench.ts",
    seed: SEED,
    captureSeconds: cap.seconds,
    roundsPerArm: rounds,
    pressRatePerMinute: cap.pressRate,
    startles: cap.escapes,
    escapesOntoPlate: cap.escapesOntoPlate,
    meanDescendingHz: cap.meanDescending,
    meanLc4Hz: cap.meanLc4,
    arms: summary,
    flyBeatsPoisson: vsPoisson,
    flyBeatsNobody: vsNobody,
    // The positive control's number is part of the result, not a debug
    // aid: without it "everyone scored zero" is unreadable.
    gameIsWinnable: oracleMedian > 0,
  };
  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, "bench.json"), JSON.stringify(report, null, 2));
  console.log(`\nwrote ${join(outDir, "bench.json")}`);
  return 0;
}

function verdict(
  vsPoisson: number,
  vsNobody: number,
  medianScore: number,
  oracleMedian: number,
): string {
  const sameAsChance = Math.abs(vsPoisson - 0.5) < 0.06;
  if (!(oracleMedian > 0)) {
    return (
      "INCONCLUSIVE: the positive control scored nothing either, so this\n" +
      "measures a game no press train can win rather than a fly that cannot\n" +
      "play it. Fix the game before reading anything else here."
    );
  }
  if (medianScore === 0 && vsNobody <= 0.56) {
    return (
      "VERDICT: the fly does not play Flappy Bird. It does not beat a coin\n" +
      `weighted to its own press rate, and a control that can see the gap\n` +
      `clears ${oracleMedian.toFixed(1)} pipes on the same pipes — so the game is winnable and\n` +
      "the fly simply does not win it. That is the honest headline, and a\n" +
      "better one than a score."
    );
  }
  if (sameAsChance) {
    return (
      "VERDICT: the fly scores no better than chance. It moves the bird,\n" +
      "but a Poisson process pressing just as often does exactly as well —\n" +
      "which is the result this benchmark exists to be able to state."
    );
  }
  return vsPoisson > 0.5
    ? "VERDICT: the fly beats its own rate-matched Poisson control. That is a\n" +
        "real claim and needs a second seed before anyone believes it."
    : "VERDICT: the fly does worse than its rate-matched control — its timing\n" +
        "is actively unhelpful, which is still a finding.";
}

process.exit(main());
