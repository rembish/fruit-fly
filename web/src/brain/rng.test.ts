import { describe, expect, it } from "vitest";
import { POISSON_KNUTH_MAX, Rng } from "./rng.js";

/** Sample mean and variance, which is what the distributions are judged on. */
function moments(draw: () => number, n: number) {
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    const v = draw();
    sum += v;
    sumSq += v * v;
  }
  const mean = sum / n;
  return { mean, variance: sumSq / n - mean * mean };
}

describe("Rng", () => {
  it("is a function of its seed and nothing else", () => {
    const a = new Rng(7);
    const b = new Rng(7);
    const c = new Rng(8);
    const first = Array.from({ length: 5 }, () => a.next());
    expect(Array.from({ length: 5 }, () => b.next())).toEqual(first);
    expect(Array.from({ length: 5 }, () => c.next())).not.toEqual(first);
  });

  it("stays inside [0, 1)", () => {
    const r = new Rng(1);
    for (let i = 0; i < 10000; i++) {
      const v = r.next();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });

  it("is uniform enough to be a noise floor", () => {
    const r = new Rng(3);
    const { mean, variance } = moments(() => r.next(), 200000);
    expect(mean).toBeCloseTo(0.5, 2);
    expect(variance).toBeCloseTo(1 / 12, 3);
  });

  it("below(n) covers the range and stays inside it", () => {
    const r = new Rng(5);
    const seen = new Set<number>();
    for (let i = 0; i < 20000; i++) {
      const v = r.below(7);
      expect(Number.isInteger(v)).toBe(true);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(7);
      seen.add(v);
    }
    expect(seen.size).toBe(7);
  });

  it("draws standard normals", () => {
    const r = new Rng(11);
    const { mean, variance } = moments(() => r.normal(), 200000);
    expect(mean).toBeCloseTo(0, 1);
    expect(variance).toBeCloseTo(1, 1);
  });
});

describe("Rng.poisson", () => {
  it("has mean and variance equal to lambda, in the Knuth regime", () => {
    // The defining property of a Poisson variable, and the one that
    // would break silently if the exact branch were wrong.
    const r = new Rng(13);
    const lambda = 4;
    const { mean, variance } = moments(() => r.poisson(lambda), 100000);
    expect(mean).toBeCloseTo(lambda, 1);
    expect(variance).toBeCloseTo(lambda, 0);
  });

  it("has mean and variance equal to lambda, in the normal regime", () => {
    // The background noise runs here: the central brain at 100 Hz over
    // a 2 ms step puts lambda in the thousands.
    const r = new Rng(17);
    const lambda = 10000;
    const { mean, variance } = moments(() => r.poisson(lambda), 20000);
    expect(mean / lambda).toBeCloseTo(1, 2);
    expect(variance / lambda).toBeCloseTo(1, 0);
  });

  it("does not jump at the boundary between its two methods", () => {
    // Two estimators of the same quantity, either side of the switch.
    // A discontinuity here would put a kink in the noise floor exactly
    // where a population's drive happens to cross it.
    const below = new Rng(19);
    const above = new Rng(23);
    const lo = moments(() => below.poisson(POISSON_KNUTH_MAX - 0.001), 60000);
    const hi = moments(() => above.poisson(POISSON_KNUTH_MAX + 0.001), 60000);
    expect(Math.abs(lo.mean - hi.mean)).toBeLessThan(0.5);
    expect(Math.abs(lo.variance - hi.variance)).toBeLessThan(3);
  });

  it("never returns a negative count", () => {
    const r = new Rng(29);
    for (let i = 0; i < 5000; i++) expect(r.poisson(31)).toBeGreaterThanOrEqual(0);
    expect(r.poisson(0)).toBe(0);
    expect(r.poisson(-1)).toBe(0);
  });
});
