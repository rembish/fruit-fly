/**
 * Leaky integrate-and-fire simulation of the whole FlyWire connectome —
 * the browser's copy of `fruitfly/brain.py`, ported line for line.
 *
 * The model and its deliberate departures from Shiu et al. 2024 are
 * documented in the Python file and not repeated here; what this file
 * documents is where the *port* had to make a choice, because that is
 * where the two can drift apart.
 *
 * The propagation is event-driven: per step only the outgoing rows of
 * neurons that actually spiked are touched, which is what keeps 2.7 M
 * connections tractable at 60 Hz. Where numpy expressed that with
 * gather/scatter gymnastics to stay out of the interpreter, this is a
 * plain nested loop, which in a JIT is the faster of the two and much
 * the clearer.
 *
 * Everything the model holds per neuron lives in a Float32Array, so the
 * state has the same precision as numpy's. Arithmetic still happens in
 * float64 and is rounded on store, which numpy does not do — one of
 * several reasons parity here is statistical.
 */

import { PARAMS, decays, pspCalibration, pyRound } from "./params.js";
import type { BrainData } from "./loader.js";
import { Rng } from "./rng.js";

export interface BrainOptions {
  dt?: number;
  noiseRate?: number;
  noiseWeight?: number;
  excGain?: number;
  inhGain?: number;
  /** Population the noise floor is delivered to; null spreads it everywhere. */
  noisePop?: string | null;
  seed?: number;
}

/** One stimulus channel: neurons, and the Hz to drive each of them at. */
export type Stimulus =
  | { pop: string; rate: number }
  | { idx: Int32Array | number[]; rate: number | Float32Array | number[] };

export class Brain {
  readonly n: number;
  readonly dt: number;
  readonly pops: Map<string, Int32Array>;

  private readonly indptr: Int32Array;
  private readonly indices: Int32Array;
  /** Signed, PSP-calibrated, gain-applied. The file's int16 stays untouched. */
  private readonly weights: Float32Array;

  private readonly v: Float32Array;
  private readonly vth: Float32Array;
  private readonly s: Float32Array; // synaptic drive, mV
  private readonly a: Float32Array; // adaptation, mV
  private readonly bias: Float32Array; // per-neuron tonic current, mV
  private readonly refract: Int32Array;
  private readonly refractSteps: number;

  private readonly decayS: number;
  private readonly decayM: number;
  private readonly decayA: number;

  // Synaptic delay ring buffer: delaySteps rows of n.
  private readonly ring: Float32Array;
  private readonly delaySteps: number;
  private ringPos = 0;

  private readonly rng: Rng;
  private noiseRate: number;
  private readonly noiseBase: number;
  private readonly noiseWeight: number;
  private readonly noiseTargets: Int32Array;
  private readonly targetRate = 1.0; // Hz/neuron, network mean
  private rateEma = 0.0;

  // Forced sensory drive: parallel arrays of neuron index and per-step
  // spike probability.
  private stimIdx = new Int32Array(0);
  private stimP = new Float32Array(0);

  /**
   * Scratch reused every step. `spiked` is written and read within one
   * step and never escapes, so allocating it per step would hand the GC
   * 60 arrays a second for nothing.
   */
  private readonly spikedBuf: Int32Array;
  private spikedCount = 0;
  /** Marks neurons already counted this step, so a forced spike that also
   *  crossed threshold is one spike and not two. numpy got this from
   *  `union1d` returning sorted unique; here it needs saying. */
  private readonly spikedMark: Uint8Array;

  t = 0.0; // simulated ms
  totalSpikes = 0;

  constructor(data: BrainData, opts: BrainOptions = {}) {
    const p = PARAMS;
    const {
      dt = 2.0,
      noiseRate = 0.0,
      noiseWeight = 0.0,
      excGain = 1.0,
      inhGain = 1.5,
      noisePop = "central",
      seed = 1,
    } = opts;

    this.dt = dt;
    this.n = data.header.n_neurons;
    this.indptr = data.indptr;
    this.indices = data.indices;
    this.pops = data.pops;
    this.rng = new Rng(seed);

    const wUnit = pspCalibration(dt, p);
    this.weights = new Float32Array(data.weights.length);
    for (let i = 0; i < data.weights.length; i++) {
      const w = data.weights[i]! * wUnit;
      this.weights[i] = w > 0 ? w * excGain : w * inhGain;
    }

    this.v = new Float32Array(this.n).fill(p.vRest);
    this.vth = new Float32Array(this.n).fill(p.vThresh);
    this.s = new Float32Array(this.n);
    this.a = new Float32Array(this.n);
    this.bias = new Float32Array(this.n);
    this.refract = new Int32Array(this.n);
    this.refractSteps = Math.max(1, pyRound(p.tRefract / dt));

    const d = decays(dt, p);
    this.decayS = d.s;
    this.decayM = d.m;
    this.decayA = d.a;

    this.delaySteps = Math.max(1, pyRound(p.delay / dt));
    this.ring = new Float32Array(this.delaySteps * this.n);

    this.noiseRate = noiseRate;
    this.noiseBase = noiseRate;
    this.noiseWeight = noiseWeight * wUnit;
    const targets = noisePop === null ? undefined : data.pops.get(noisePop);
    if (targets && targets.length > 0) {
      this.noiseTargets = targets;
    } else {
      // Noise everywhere is the fallback, not the intent: the optic
      // lobes are ~100k of the 139k neurons and are meant to be driven
      // by actual light. Noise in there makes the fly hallucinate
      // looming objects.
      this.noiseTargets = new Int32Array(this.n);
      for (let i = 0; i < this.n; i++) this.noiseTargets[i] = i;
    }

    this.spikedBuf = new Int32Array(this.n);
    this.spikedMark = new Uint8Array(this.n);

    // Constructor order matters and mirrors Python's: vth is filled
    // uniformly, and only then does the giant fiber get its higher
    // threshold. It is one of the largest neurons in the fly and is
    // known for exactly that; the paper's uniform threshold leaves it
    // chronically excitable in a spontaneously active network.
    this.shiftThreshold("GF", 10.0);
  }

  /**
   * Where the noise governor currently sits, in Hz per neuron.
   *
   * Worth reading rather than assuming: it can only *raise* the floor,
   * and this network is already livelier than the 1.0 Hz/neuron it aims
   * at, so it empties to zero within about ten simulated seconds and
   * stays there. The parity gate compares it, because two ports whose
   * rates agreed while their governors sat in different places would be
   * agreeing by luck.
   */
  get noiseFloor(): number {
    return this.noiseRate;
  }

  shiftThreshold(pop: string, deltaMv: number): void {
    const idx = this.pops.get(pop);
    if (!idx) return;
    for (let i = 0; i < idx.length; i++) {
      const j = idx[i]!;
      this.vth[j] = this.vth[j]! + deltaMv;
    }
  }

  /** Fresh dynamical state, same anatomy: a new fly's brain. */
  resetState(): void {
    this.v.fill(PARAMS.vRest);
    this.s.fill(0);
    this.a.fill(0);
    this.refract.fill(0);
    this.ring.fill(0);
    this.noiseRate = this.noiseBase;
    this.rateEma = 0;
    this.stimIdx = new Int32Array(0);
    this.stimP = new Float32Array(0);
  }

  /**
   * Forced firing rates for sensory neurons, as Poisson processes — the
   * optogenetic-style activation of Shiu et al. A per-neuron rate array
   * is how the retina drives every photoreceptor at its own rate.
   */
  setStimulus(stim: Stimulus[]): void {
    const idxParts: number[] = [];
    const pParts: number[] = [];
    const scale = this.dt * 1e-3;
    for (const item of stim) {
      const idx = "pop" in item ? this.pops.get(item.pop) : item.idx;
      if (!idx || idx.length === 0) continue;
      const rate = item.rate;
      if (typeof rate === "number") {
        if (rate <= 0) continue;
        const p = rate * scale;
        for (let i = 0; i < idx.length; i++) {
          idxParts.push(idx[i]!);
          pParts.push(p);
        }
      } else {
        for (let i = 0; i < idx.length; i++) {
          const r = rate[i]!;
          if (r > 0) {
            idxParts.push(idx[i]!);
            pParts.push(r * scale);
          }
        }
      }
    }
    this.stimIdx = Int32Array.from(idxParts);
    this.stimP = Float32Array.from(pParts);
  }

  /**
   * Advance one dt. Returns a view of the neurons that spiked, valid
   * until the next call — copy it if you need to keep it.
   */
  step(): Int32Array {
    const p = PARAMS;
    const { n, dt, v, s, a, vth, bias, refract, ring } = this;
    const ringBase = this.ringPos * n;

    // Deliver the synaptic input that left its presynaptic neuron
    // delay ms ago, and decay what is already in flight.
    for (let i = 0; i < n; i++) {
      s[i] = s[i]! * this.decayS + ring[ringBase + i]!;
      ring[ringBase + i] = 0;
    }

    // Background noise: draw the total event count once and scatter it,
    // which is far cheaper than a draw per neuron. Straight into `s`,
    // with no intermediate array — at ~10k events a step, an allocation
    // here would be the whole cost of the step.
    if (this.noiseRate > 0 && this.noiseWeight > 0) {
      const m = this.noiseTargets.length;
      const lam = m * this.noiseRate * dt * 1e-3;
      const k = this.rng.poisson(lam);
      for (let j = 0; j < k; j++) {
        const i = this.noiseTargets[this.rng.below(m)]!;
        s[i] = s[i]! + this.noiseWeight;
      }
    }

    // Membrane integration with spike-frequency adaptation. Exponential
    // Euler: exact for input held constant across the step, and
    // unconditionally stable. Everyone is integrated and the few
    // refractory neurons are clamped back afterwards, as in Python.
    this.spikedCount = 0;
    for (let i = 0; i < n; i++) {
      a[i] = a[i]! * this.decayA;
      const vInf = p.vRest + s[i]! - a[i]! + bias[i]!;
      let vi = vInf + (v[i]! - vInf) * this.decayM;
      const r = refract[i]!;
      if (r > 0) {
        vi = p.vReset;
        refract[i] = r - 1;
      }
      v[i] = vi;
      if (vi >= vth[i]!) {
        this.spikedBuf[this.spikedCount++] = i;
        this.spikedMark[i] = 1;
      }
    }

    // Forced sensory spikes, Poisson at the commanded rate. A neuron in
    // its refractory period cannot be forced, and one that already
    // crossed threshold this step must not be counted twice.
    for (let j = 0; j < this.stimIdx.length; j++) {
      if (this.rng.next() < this.stimP[j]!) {
        const i = this.stimIdx[j]!;
        if (refract[i]! <= 0 && this.spikedMark[i] === 0) {
          this.spikedBuf[this.spikedCount++] = i;
          this.spikedMark[i] = 1;
        }
      }
    }

    const count = this.spikedCount;
    if (count > 0) {
      const slot = ((this.ringPos + this.delaySteps - 1) % this.delaySteps) * n;
      for (let j = 0; j < count; j++) {
        const i = this.spikedBuf[j]!;
        v[i] = p.vReset;
        refract[i] = this.refractSteps;
        a[i] = a[i]! + p.adaptB;
        this.spikedMark[i] = 0;
        const end = this.indptr[i + 1]!;
        for (let e = this.indptr[i]!; e < end; e++) {
          const target = slot + this.indices[e]!;
          ring[target] = ring[target]! + this.weights[e]!;
        }
      }
      this.totalSpikes += count;
    }

    // Noise-floor governor. A stability governor on an invented noise
    // floor, not arousal: it raises the floor when the network goes
    // quiet and backs off when it rages, which is what keeps it out of
    // the coma/seizure pair it otherwise collapses into.
    const inst = (count * 1000.0) / (n * dt);
    this.rateEma += (inst - this.rateEma) * (dt / 500.0);
    if (this.noiseBase > 0) {
      const err = this.targetRate - this.rateEma;
      this.noiseRate += err * (dt / 200.0) * this.noiseBase * 0.1;
      this.noiseRate = Math.min(
        Math.max(this.noiseRate, 0),
        this.noiseBase * 3.0,
      );
    }

    this.ringPos = (this.ringPos + 1) % this.delaySteps;
    this.t += dt;
    return this.spikedBuf.subarray(0, count);
  }
}

/** Exponential moving average firing rate (Hz/neuron) per population. */
export class RateMonitor {
  readonly names: string[];
  private readonly sizes: Float64Array;
  private readonly rate: Float64Array;
  private readonly hits: Float64Array;
  private readonly decay: number;
  private readonly gain: number;
  /** Neuron -> which watched populations it belongs to, CSR-style. */
  private readonly memberOffsets: Int32Array;
  private readonly memberSlots: Int32Array;

  constructor(brain: Brain, names: string[], tauMs = 100.0) {
    this.names = names.filter((n) => (brain.pops.get(n)?.length ?? 0) > 0);
    this.decay = Math.exp(-brain.dt / tauMs);
    this.gain = ((1.0 - this.decay) * 1000.0) / brain.dt;
    this.sizes = new Float64Array(this.names.length);
    this.rate = new Float64Array(this.names.length);
    this.hits = new Float64Array(this.names.length);

    // Python asks "is this spike in that population" with one boolean
    // mask per population, which costs populations x spikes per step.
    // Inverted into a per-neuron membership table it costs just spikes,
    // and a step can spike thousands of times. A neuron needs a list
    // rather than a slot because the populations overlap — GF sits
    // inside descending, DNa02_L inside DNa02.
    const counts = new Int32Array(brain.n + 1);
    this.names.forEach((name, slot) => {
      const idx = brain.pops.get(name)!;
      this.sizes[slot] = idx.length;
      for (let i = 0; i < idx.length; i++) counts[idx[i]!]! += 1;
    });
    const offsets = new Int32Array(brain.n + 1);
    let total = 0;
    for (let i = 0; i < brain.n; i++) {
      offsets[i] = total;
      total += counts[i]!;
    }
    offsets[brain.n] = total;
    const slots = new Int32Array(total);
    const at = offsets.slice(0, brain.n);
    this.names.forEach((name, slot) => {
      const idx = brain.pops.get(name)!;
      for (let i = 0; i < idx.length; i++) slots[at[idx[i]!]!++] = slot;
    });
    this.memberOffsets = offsets;
    this.memberSlots = slots;
  }

  update(spiked: Int32Array): void {
    this.hits.fill(0);
    for (let j = 0; j < spiked.length; j++) {
      const i = spiked[j]!;
      const end = this.memberOffsets[i + 1]!;
      for (let e = this.memberOffsets[i]!; e < end; e++) {
        this.hits[this.memberSlots[e]!]! += 1;
      }
    }
    for (let slot = 0; slot < this.rate.length; slot++) {
      this.rate[slot] =
        this.rate[slot]! * this.decay +
        (this.gain * this.hits[slot]!) / this.sizes[slot]!;
    }
  }

  get(name: string): number {
    const slot = this.names.indexOf(name);
    return slot < 0 ? 0 : this.rate[slot]!;
  }

  /** All watched rates, for callers that want to post them somewhere. */
  snapshot(): Record<string, number> {
    const out: Record<string, number> = {};
    this.names.forEach((name, slot) => {
      out[name] = this.rate[slot]!;
    });
    return out;
  }
}
