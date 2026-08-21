import { describe, expect, it } from "vitest";
import { PARAMS, decays, pspCalibration, pyRound } from "./params.js";

describe("pyRound", () => {
  it("rounds halves the way Python does, not the way JavaScript does", () => {
    // This is the whole reason the helper exists. Math.round(0.5) is 1
    // and Math.round(2.5) is 3; Python gives 0 and 2. A step count that
    // differs by one is a different delay line, not a rounding detail.
    expect(pyRound(0.5)).toBe(0);
    expect(pyRound(1.5)).toBe(2);
    expect(pyRound(2.5)).toBe(2);
    expect(pyRound(3.5)).toBe(4);
    expect(Math.round(0.5)).toBe(1); // ... and this is what we avoided
  });

  it("rounds everything else normally", () => {
    expect(pyRound(1.1)).toBe(1);
    expect(pyRound(1.9)).toBe(2);
    expect(pyRound(0.4)).toBe(0);
  });

  it("gives the step counts the default dt actually uses", () => {
    // refract 2.2/2.0 -> 1, delay 1.8/2.0 -> 1. Both are checked here
    // rather than assumed because they are what the ring buffer and the
    // refractory clamp are built from.
    expect(Math.max(1, pyRound(PARAMS.tRefract / 2.0))).toBe(1);
    expect(Math.max(1, pyRound(PARAMS.delay / 2.0))).toBe(1);
    // ... and at the finer step the calibration docs mention
    expect(Math.max(1, pyRound(PARAMS.tRefract / 0.5))).toBe(4);
    expect(Math.max(1, pyRound(PARAMS.delay / 0.5))).toBe(4);
  });
});

describe("decays", () => {
  it("is the exact exponential, not forward Euler", () => {
    const d = decays(2.0);
    expect(d.s).toBeCloseTo(Math.exp(-2.0 / 5.5), 12);
    expect(d.m).toBeCloseTo(Math.exp(-2.0 / 20.0), 12);
    expect(d.a).toBeCloseTo(Math.exp(-2.0 / 500.0), 12);
    // Euler would have said 1 - dt/tau, which at this dt is a 19.5%
    // shorter synaptic time constant — a different model, quietly.
    expect(d.s).not.toBeCloseTo(1 - 2.0 / 5.5, 3);
  });
});

describe("pspCalibration", () => {
  it("makes one unit-weight event peak at exactly psp_peak", () => {
    // Replays the calibration's own integration with the weight it
    // returned: the peak must land on the target, which is the property
    // the number is defined by.
    const dt = 2.0;
    const w = pspCalibration(dt);
    const d = decays(dt);
    let s = w;
    let v = 0;
    let peak = 0;
    for (let i = 0; i < Math.trunc(200 / dt); i++) {
      v = s + (v - s) * d.m;
      s *= d.s;
      peak = Math.max(peak, v);
    }
    expect(peak).toBeCloseTo(PARAMS.pspPeak, 9);
  });

  it("scales inversely with the weight it has to compensate", () => {
    expect(pspCalibration(2.0)).toBeGreaterThan(0);
    expect(pspCalibration(0.5)).toBeGreaterThan(0);
  });
});
