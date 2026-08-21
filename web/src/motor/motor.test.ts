import { describe, expect, it } from "vitest";
import {
  ESCAPE,
  FLYING,
  LANDED,
  MotorMap,
  SPLAT_S,
  SQUASHED,
  TAKEOFF,
} from "./motor.js";

const W = 960;
const H = 540;
const DT = 1 / 60;

/** Rates that keep a flying fly flying and a landed fly landed. */
const CALM = {
  DNa02_L: 10,
  DNa02_R: 10,
  descending: 5.2,
  DNp09: 1.6,
  MDN: 9,
};

/**
 * Drive the map for `seconds` with fixed inputs.
 *
 * Returns every phase seen and the peak speed, not just the final state:
 * an escape lasts 0.22 s and then hands back to flight, so "did it
 * escape" is a question about the whole run and asserting on the last
 * frame would only ever catch a run that happened to end mid-dart.
 */
function run(
  m: MotorMap,
  seconds: number,
  opts: {
    t0?: number;
    rates?: Record<string, number>;
    gf?: number;
    threat?: number;
    bearing?: number;
  } = {},
): { t: number; seen: Set<string>; peakSpeed: number; escapeHeading: number } {
  const { t0 = 0, rates = CALM, gf = 0, threat = 0, bearing = 0 } = opts;
  let t = t0;
  let peakSpeed = 0;
  let escapeHeading = NaN;
  const seen = new Set<string>();
  const steps = Math.round(seconds / DT);
  for (let i = 0; i < steps; i++) {
    t += DT;
    m.update(DT, t, rates, gf, bearing, threat);
    seen.add(m.st.state);
    peakSpeed = Math.max(peakSpeed, m.st.speed);
    if (m.st.state === ESCAPE && Number.isNaN(escapeHeading)) {
      escapeHeading = m.st.heading;
    }
  }
  return { t, seen, peakSpeed, escapeHeading };
}

describe("giant fiber readout", () => {
  it("treats a lone spike as a jink, not an escape", () => {
    // The GF fires sporadically at rest in this model. If a single spike
    // escaped, the fly would spend its life bolting.
    const m = new MotorMap(W, H, 1);
    m.st.state = FLYING;
    m.st.speed = 300;
    const before = m.st.heading;
    m.update(DT, 1.0, CALM, 1, 0, 0);
    expect(m.st.state).toBe(FLYING);
    expect(m.st.lastEvent).toContain("jink");
    expect(m.st.heading).not.toBe(before);
  });

  it("escapes only on a sustained burst", () => {
    // One spike per frame at 60 fps is 60 Hz sustained, which is what a
    // looming stimulus produces and is twice the 30 Hz threshold.
    const quiet = new MotorMap(W, H, 1);
    quiet.st.state = FLYING;
    // A spike every twentieth frame is 3 Hz: the resting hum, and it
    // must not escape however long it goes on for.
    let t = 0;
    for (let i = 0; i < 600; i++) {
      t += DT;
      quiet.update(DT, t, CALM, i % 20 === 0 ? 1 : 0, 0, 0);
      expect(quiet.st.state).not.toBe(ESCAPE);
    }

    const m = new MotorMap(W, H, 1);
    m.st.state = FLYING;
    const r = run(m, 1.0, { gf: 1, threat: 0.9, bearing: 0 });
    expect(r.seen.has(ESCAPE)).toBe(true);
    expect(r.peakSpeed).toBe(1400);
  });

  it("darts away from the threat rather than toward it", () => {
    const m = new MotorMap(W, H, 1);
    m.st.state = FLYING;
    // Threat due east; the escape heading should point broadly west,
    // within the +/-0.7 rad scatter the model adds.
    const r = run(m, 1.0, { gf: 1, threat: 0.9, bearing: 0 });
    expect(r.seen.has(ESCAPE)).toBe(true);
    expect(Math.cos(r.escapeHeading)).toBeLessThan(0.8);
  });

  it("has to get airborne before it can flee the ground", () => {
    // The flyswatter window: a real fly needs 100-200 ms to take off
    // after its escape circuit fires, and it is squashable throughout.
    const m = new MotorMap(W, H, 1);
    m.st.state = LANDED;
    m.update(DT, 1.0, CALM, 40, 0, 0.9);
    expect(m.st.state).toBe(TAKEOFF);
    expect(m.st.speed).toBe(0);
    const r = run(m, 0.4, { t0: 1.0, gf: 0, threat: 0.9 });
    // TAKEOFF first, then the dart — in that order, never straight to it.
    expect(r.seen.has(TAKEOFF)).toBe(true);
    expect(r.seen.has(ESCAPE)).toBe(true);
    expect(r.peakSpeed).toBe(1400);
  });
});

describe("threat", () => {
  it("startles a sitting fly when the cursor looms", () => {
    const m = new MotorMap(W, H, 1);
    m.st.state = LANDED;
    m.update(DT, 1.0, CALM, 0, 0, 0.9);
    expect(m.st.state).toBe(TAKEOFF);
    expect(m.st.lastEvent).toContain("looming");
  });

  it("makes landing reluctant, never impossible", () => {
    // The bug this guards: zeroing the calm accumulator under any threat
    // meant a fly with the cursor anywhere near it could never land, and
    // measured 0% ground time while hovering. Threat scales it instead.
    const m = new MotorMap(W, H, 7);
    m.st.state = FLYING;
    // Threat below the 0.5 startle line but well above the old 0.05 gate
    // that used to zero the accumulator outright.
    const r = run(m, 30, { threat: 0.3, rates: { ...CALM, descending: 3.0 } });
    expect(r.seen.has(LANDED)).toBe(true);
  });
});

describe("flight", () => {
  it("steers toward the more active DNa02 side", () => {
    // DNa02 drives turns toward its own side; screen y grows downward, so
    // a right-side excess should increase the heading angle.
    const m = new MotorMap(W, H, 3);
    m.st.state = FLYING;
    m.st.heading = 0;
    m.st.x = W / 2;
    m.st.y = H / 2;
    const rates = { ...CALM, DNa02_L: 5, DNa02_R: 40, descending: 4.0 };
    for (let i = 0; i < 30; i++) m.update(DT, 1 + i * DT, rates, 0, 0, 0);
    expect(m.st.heading).toBeGreaterThan(0);
  });

  it("lands when the descending pool goes quiet", () => {
    const m = new MotorMap(W, H, 5);
    m.st.state = FLYING;
    run(m, 10, { rates: { ...CALM, descending: 2.0 } });
    expect(m.st.state).toBe(LANDED);
    expect(m.st.speed).toBe(0);
  });

  it("takes off when the descending pool gets loud", () => {
    const m = new MotorMap(W, H, 5);
    m.st.state = LANDED;
    run(m, 10, { rates: { ...CALM, descending: 14.0, DNp09: 4.0 } });
    expect([TAKEOFF, FLYING, ESCAPE]).toContain(m.st.state);
  });

  it("stays on the canvas", () => {
    const m = new MotorMap(W, H, 9);
    m.st.state = FLYING;
    m.st.speed = 900;
    run(m, 20, { rates: { ...CALM, descending: 9.0 } });
    expect(m.st.x).toBeGreaterThanOrEqual(24);
    expect(m.st.x).toBeLessThanOrEqual(W - 24);
    expect(m.st.y).toBeGreaterThanOrEqual(24);
    expect(m.st.y).toBeLessThanOrEqual(H - 24);
  });
});

describe("swats", () => {
  it("squashes a fly that was still on the ground", () => {
    const m = new MotorMap(W, H, 1);
    m.st.state = LANDED;
    m.squash(1.0);
    expect(m.st.state).toBe(SQUASHED);
    expect(m.st.lastEvent).toBe("SPLAT.");
  });

  it("sends a new fly in after the splat has had its moment", () => {
    const m = new MotorMap(W, H, 1);
    m.squash(1.0);
    run(m, SPLAT_S - 0.5, { t0: 1.0 });
    expect(m.st.state).toBe(SQUASHED);
    run(m, 1.0, { t0: 1.0 + SPLAT_S - 0.5 });
    expect(m.st.state).toBe(FLYING);
    expect(m.st.lastEvent).toContain("window");
  });

  it("only clips a fly that was airborne", () => {
    const m = new MotorMap(W, H, 1);
    m.st.state = FLYING;
    m.glancingBlow(1.0);
    expect(m.st.state).toBe(ESCAPE);
    expect(m.st.lastEvent).toContain("glancing");
  });
});

describe("determinism", () => {
  it("is a function of its seed", () => {
    const a = new MotorMap(W, H, 42);
    const b = new MotorMap(W, H, 42);
    a.st.state = FLYING;
    b.st.state = FLYING;
    const rates = { ...CALM, descending: 7.0 };
    run(a, 5, { rates });
    run(b, 5, { rates });
    expect(a.st.x).toBe(b.st.x);
    expect(a.st.y).toBe(b.st.y);
    expect(a.st.heading).toBe(b.st.heading);
  });
});
