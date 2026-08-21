/**
 * Screen patches -> photoreceptor firing rates, per eye column.
 *
 * Port of `fruitfly/senses.py`'s `Retina`. Vision here is retinotopic and
 * real: each eye is the actual hexagonal lattice of ~790 columns from the
 * FlyWire column assignments, and every photoreceptor is driven at its own
 * rate from the luminance its own column sees.
 *
 * The transfer functions below are computed here rather than left to the
 * network on purpose, and the reason is in the README: photoreceptors and
 * lamina monopolar cells are graded, non-spiking neurons, which a spiking
 * LIF represents poorly. So phototransduction and the lamina's transient
 * OFF response are computed in this layer and injected at L1/L2/L3 per
 * column; the real network begins at the lamina's *output* synapses.
 */

/** Retina sampling grid, pixels per eye. Matches `senses.py`. */
export const PATCH = 96;
/** Pixels from the fly to each eye's gaze centre. */
export const EYE_OFFSET = 80.0;
/** Pixels of screen each eye sees — half-width of the sampled patch. */
export const EYE_RADIUS = 120.0;

export type Eye = "L" | "R";

/** The per-eye arrays the exporter ships under `retina_*`. */
export interface RetinaData {
  /** Photoreceptor neuron indices. */
  idx: Int32Array;
  /** Column ordinal per photoreceptor. */
  col: Int32Array;
  /** L1/L2/L3 neuron indices. */
  lamIdx: Int32Array;
  /** Column ordinal per lamina cell. */
  lamCol: Int32Array;
  /** Per-column position on the unit disc, (ncols, 2) flattened. */
  xy: Float32Array;
}

interface EyeState extends RetinaData {
  /** Column -> patch pixel, flattened (x, y) pairs. */
  px: Int32Array;
  /** Slowly-adapting luminance baseline, per column. */
  baseline: Float32Array;
  /** Scratch, reused per frame so a 60 Hz loop allocates nothing. */
  colRates: Float32Array;
  lamRates: Float32Array;
  outPhoto: Float32Array;
  outLam: Float32Array;
}

/** One stimulus channel ready for `Brain.setStimulus`. */
export interface RateChannel {
  idx: Int32Array;
  rate: Float32Array;
}

export class Retina {
  // Photoreceptors release continuously in the light. Their drive is
  // histaminergic and so inhibitory in the compiled connectome, which is
  // what the medulla reads.
  static readonly R_TONIC = 5.0; // Hz in darkness
  static readonly GAIN = 40.0; // Hz per unit of contrast
  static readonly LUM_GAIN = 45.0; // Hz per unit of absolute luminance
  static readonly R_MAX = 70.0; // Hz ceiling
  static readonly TAU_ADAPT = 1.5; // s, baseline adaptation

  // Lamina OFF response: transient firing on local darkening against the
  // adapted baseline.
  static readonly L_R0 = 1.0; // Hz at steady state
  static readonly L_GAIN = 90.0; // Hz per unit of darkening
  static readonly L_MAX = 100.0; // Hz ceiling

  private readonly eyes: Record<Eye, EyeState>;

  constructor(data: Record<Eye, RetinaData>) {
    const build = (d: RetinaData): EyeState => {
      const ncols = d.xy.length / 2;
      const px = new Int32Array(ncols * 2);
      for (let c = 0; c < ncols; c++) {
        // Unit disc [-1, 1] -> patch pixel, the same mapping Python does
        // with a clip at both ends.
        for (let k = 0; k < 2; k++) {
          const v = (d.xy[c * 2 + k]! * 0.5 + 0.5) * (PATCH - 1);
          px[c * 2 + k] = Math.min(PATCH - 1, Math.max(0, Math.trunc(v)));
        }
      }
      return {
        ...d,
        px,
        baseline: new Float32Array(ncols).fill(0.5),
        colRates: new Float32Array(ncols),
        lamRates: new Float32Array(ncols),
        outPhoto: new Float32Array(d.idx.length),
        outLam: new Float32Array(d.lamIdx.length),
      };
    };
    this.eyes = { L: build(data.L), R: build(data.R) };
  }

  /**
   * One eye: a luminance patch in [0, 1] -> the rates its neurons fire at.
   *
   * `cursorPx` is the cursor's position in patch pixel coordinates, or
   * null when it is out of view, and `cursorR` its perspective-scaled
   * radius. The cursor is drawn *into* the retina rather than sampled
   * from the canvas, exactly as on the desktop: the screen has no depth,
   * so the approach is simulated at the renderer and the detection
   * happens in the fly's own optic lobe.
   *
   * `dt` is in **simulated** seconds. The desktop passes wall seconds and
   * gets away with it because it runs at about 1x; here the brain sets
   * the pace, and feeding wall time to a 1.5 s adaptation constant would
   * adapt at the wrong speed whenever the machine is slow.
   */
  process(
    eye: Eye,
    patch: Float32Array | null,
    cursorPx: readonly [number, number] | null,
    cursorR: number,
    dt: number,
  ): RateChannel[] {
    const E = this.eyes[eye];
    if (!patch) return [];

    const ncols = E.baseline.length;
    const adapt = Math.min(1.0, dt / Retina.TAU_ADAPT);
    const cursorR2 = cursorR * cursorR;

    for (let c = 0; c < ncols; c++) {
      const x = E.px[c * 2]!;
      const y = E.px[c * 2 + 1]!;
      let lum = patch[y * PATCH + x]!;

      if (cursorPx && cursorR > 0) {
        const dx = x - cursorPx[0];
        const dy = y - cursorPx[1];
        if (dx * dx + dy * dy <= cursorR2) lum *= 0.1;
      }

      const base = E.baseline[c]!;
      // Darkening is measured against the OLD baseline, before the update
      // — the transient is the change, not the state after it.
      const darkening = Math.max(0, base - lum);
      const newBase = base + (lum - base) * adapt;
      E.baseline[c] = newBase;
      const contrast = lum - newBase;

      E.colRates[c] = Math.min(
        Retina.R_MAX,
        Math.max(
          0,
          Retina.R_TONIC + Retina.GAIN * contrast + Retina.LUM_GAIN * lum,
        ),
      );
      E.lamRates[c] = Math.min(
        Retina.L_MAX,
        Math.max(0, Retina.L_R0 + Retina.L_GAIN * darkening),
      );
    }

    for (let i = 0; i < E.idx.length; i++) E.outPhoto[i] = E.colRates[E.col[i]!]!;
    for (let i = 0; i < E.lamIdx.length; i++) {
      E.outLam[i] = E.lamRates[E.lamCol[i]!]!;
    }
    return [
      { idx: E.idx, rate: E.outPhoto },
      { idx: E.lamIdx, rate: E.outLam },
    ];
  }
}

/** Pull the per-eye arrays out of the map the loader returns. */
export function retinaFromSections(
  sections: Map<string, Int32Array | Float32Array>,
): Record<Eye, RetinaData> {
  const eye = (e: Eye): RetinaData => ({
    idx: sections.get(`${e}_idx`) as Int32Array,
    col: sections.get(`${e}_col`) as Int32Array,
    lamIdx: sections.get(`${e}_lam_idx`) as Int32Array,
    lamCol: sections.get(`${e}_lam_col`) as Int32Array,
    xy: sections.get(`${e}_xy`) as Float32Array,
  });
  return { L: eye("L"), R: eye("R") };
}
