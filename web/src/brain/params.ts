/**
 * The model constants, and the two derivations both runtimes must agree
 * on. Ported from `fruitfly/brain.py`; the numbers are Shiu et al. 2024
 * except where that file documents a deliberate difference.
 */

export const PARAMS = {
  vRest: -52.0, // mV
  vReset: -52.0, // mV
  vThresh: -45.0, // mV
  tauM: 20.0, // ms, membrane
  tauSyn: 5.5, // ms, synaptic
  tRefract: 2.2, // ms
  delay: 1.8, // ms, synaptic
  pspPeak: 0.275, // mV from one synapse at rest
  adaptB: 8.0, // mV of adaptation per spike
  tauAdapt: 500.0, // ms, adaptation decay
} as const;

export interface Decays {
  s: number;
  m: number;
  a: number;
}

/**
 * Per-step decay factors: exp(-dt/tau), not forward Euler.
 *
 * Euler does not merely add error, it rescales the model — at dt=2 ms it
 * turns tau_syn 5.5 into an effective 4.42. The exact factor samples the
 * true exponential at any dt, so dt costs spike-timing resolution and
 * nothing else.
 */
export function decays(dt: number, p = PARAMS): Decays {
  return {
    s: Math.exp(-dt / p.tauSyn),
    m: Math.exp(-dt / p.tauM),
    a: Math.exp(-dt / p.tauAdapt),
  };
}

/**
 * Weight such that one unit-weight synaptic event peaks at pspPeak mV.
 *
 * Simulates the linear membrane response to a single impulse with the
 * same scheme and the same decay factors used at runtime, then rescales.
 * This is the one constant both runtimes *derive* rather than read from
 * the file, so it is the one most able to drift apart — the parity
 * reference carries Python's value and a test holds this to it.
 *
 * `Math.trunc` rather than `Math.floor`: Python's `int()` truncates, and
 * although dt is positive today the two disagree the moment it is not.
 */
export function pspCalibration(dt: number, p = PARAMS): number {
  const d = decays(dt, p);
  let s = 1.0;
  let v = 0.0;
  let peak = 0.0;
  const steps = Math.trunc(200 / dt);
  for (let i = 0; i < steps; i++) {
    v = s + (v - s) * d.m; // v measured from rest; v_inf = s
    s *= d.s;
    peak = Math.max(peak, v);
  }
  return p.pspPeak / peak;
}

/**
 * Python's `int(round(x))` for the step counts.
 *
 * Not `Math.round`. Python rounds halves to even and JavaScript rounds
 * them up, so `round(0.5)` is 0 there and 1 here — and a step count that
 * differs by one is a different delay line, not a rounding detail. The
 * live values (2.2/2.0 and 1.8/2.0 at the default dt) are nowhere near a
 * half, but dt is a knob and the next value someone tries might be.
 */
export function pyRound(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}
