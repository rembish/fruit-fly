/**
 * Seeded randomness for the brain, and the two distributions it needs.
 *
 * The port cannot share numpy's PCG64, so it does not try: parity with
 * the Python reference is statistical and spike-exact agreement is
 * explicitly not a goal. What this must be is *seeded* — the same seed
 * gives the same fly twice — and fast enough to be called tens of
 * thousands of times per simulated step without showing up in a profile.
 *
 * mulberry32: one 32-bit word of state, a handful of ops, and it passes
 * gjrand's smallcrush, which is far beyond what a noise floor asks of
 * it. The one property that matters here is that it does not correlate
 * with itself over the short runs a single step makes.
 */

export class Rng {
  private s: number;

  constructor(seed: number) {
    // A zero seed leaves mulberry32 in a fixed point for its first
    // outputs; the golden-ratio offset is the usual guard and costs
    // nothing.
    this.s = (seed ^ 0x9e3779b9) >>> 0;
  }

  /** Uniform in [0, 1). */
  next(): number {
    this.s = (this.s + 0x6d2b79f5) >>> 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Uniform integer in [0, n). */
  below(n: number): number {
    return (this.next() * n) | 0;
  }

  /** Uniform in [lo, hi), matching Python's `random.uniform`. */
  uniform(lo: number, hi: number): number {
    return lo + (hi - lo) * this.next();
  }

  /** One of the given values, matching Python's `random.choice`. */
  pick<T>(items: readonly T[]): T {
    return items[this.below(items.length)]!;
  }

  /** Either -1 or +1, which is what `choice((-1, 1))` is always used for. */
  sign(): number {
    return this.next() < 0.5 ? -1 : 1;
  }

  /**
   * Standard normal, Box-Muller.
   *
   * Cached in pairs because the transform produces two independent
   * draws and throwing one away doubles the cost of the Poisson
   * approximation below, which is the hot path.
   */
  private spare: number | null = null;

  normal(): number {
    if (this.spare !== null) {
      const v = this.spare;
      this.spare = null;
      return v;
    }
    // next() can return exactly 0 and log(0) is -Infinity; the standard
    // guard is to resample, which happens about once every four billion
    // draws.
    let u = this.next();
    while (u === 0) u = this.next();
    const r = Math.sqrt(-2 * Math.log(u));
    const theta = 2 * Math.PI * this.next();
    this.spare = r * Math.sin(theta);
    return r * Math.cos(theta);
  }

  /**
   * Poisson count with mean `lambda`.
   *
   * Two regimes, because the network uses both. Knuth's product method
   * is exact and costs O(lambda) draws, which is right for the handful
   * of events a small population contributes. The background noise runs
   * at lambda in the thousands — the central brain is ~50k neurons at
   * 100 Hz over a 2 ms step — where Knuth would draw thousands of
   * uniforms per step and the normal approximation is both accurate
   * (the distribution is symmetric to well under a percent by then) and
   * a single pair of draws.
   */
  poisson(lambda: number): number {
    if (lambda <= 0) return 0;
    if (lambda < POISSON_KNUTH_MAX) {
      const limit = Math.exp(-lambda);
      let k = 0;
      let p = 1;
      do {
        k += 1;
        p *= this.next();
      } while (p > limit);
      return k - 1;
    }
    const k = Math.round(lambda + Math.sqrt(lambda) * this.normal());
    return k < 0 ? 0 : k;
  }
}

/** Where Knuth stops being cheap and the normal approximation is honest. */
export const POISSON_KNUTH_MAX = 30;
