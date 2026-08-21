/**
 * Sense the world -> brain stimuli, threat, and where the threat is.
 *
 * Port of `fruitfly/senses.py`'s `Senses`. Two channels reach the brain:
 * the eyes, which are real retinotopic pixels through real photoreceptors,
 * and a scaled-down direct injection into the LC4/LPLC2 looming detectors.
 *
 * That injection is a safety net and it is disclosed rather than hidden:
 * M0.3 measured what the eyes alone do with an approaching object and
 * found they move the loom detectors by half but never reach the giant
 * fiber. The desktop keeps the injection at 0.4 for exactly that reason,
 * and so does this. Set it to 0 to trust the eyes completely and watch
 * the fly stop escaping.
 */

import { EYE_OFFSET, EYE_RADIUS, PATCH, type Eye, type RateChannel, Retina } from "./retina.js";

/** What the main thread samples and hands over each sensory tick. */
export interface SensoryFrame {
  cursorX: number;
  cursorY: number;
  patchL: Float32Array | null;
  patchR: Float32Array | null;
  /** Simulated seconds since the previous patches. */
  patchDt: number;
}

export interface SensedWorld {
  /** Per-neuron rate channels, ready for `Brain.setStimulus`. */
  channels: RateChannel[];
  /** Named-population drive: the loom injection, and swats. */
  pops: { pop: string; rate: number }[];
  /** 0..1, how alarming the cursor currently is. */
  threat: number;
  /** Absolute bearing to the cursor, radians in screen coords. */
  bearing: number;
}

export interface SensesOptions {
  /** 0 disables the direct LC4/LPLC2 injection: pure retina. */
  loomInjection?: number;
  loomRadius?: number;
  panicRadius?: number;
  loomRateMax?: number;
  approachGain?: number;
}

export class Senses {
  private readonly loomInjection: number;
  private readonly loomRadius: number;
  private readonly panicRadius: number;
  private readonly loomRateMax: number;
  private readonly approachGain: number;

  private lastDist = 1e9;
  private lastT = 0;

  constructor(
    private readonly retina: Retina | null,
    opts: SensesOptions = {},
  ) {
    const {
      loomInjection = 0.4,
      loomRadius = 260.0,
      panicRadius = 110.0,
      loomRateMax = 120.0,
      approachGain = 0.12,
    } = opts;
    this.loomInjection = loomInjection;
    this.loomRadius = loomRadius;
    this.panicRadius = panicRadius;
    this.loomRateMax = loomRateMax;
    this.approachGain = approachGain;
  }

  /** Where an eye is looking, given where the fly is and which way it faces. */
  static eyeCentre(
    flyX: number,
    flyY: number,
    heading: number,
    eye: Eye,
  ): [number, number] {
    const side = eye === "L" ? -1.0 : 1.0;
    const ang = heading + (side * Math.PI) / 2;
    return [flyX + Math.cos(ang) * EYE_OFFSET, flyY + Math.sin(ang) * EYE_OFFSET];
  }

  /**
   * The cursor's place in one eye's patch, and how big it looks.
   *
   * The screen is flat, so the approach is simulated here: the rendered
   * radius grows as the cursor nears the fly. This is the perspective the
   * loom detectors are given; without it a cursor crossing the eye is a
   * translation and, as M0.3 measured, translation does not reach them.
   */
  cursorInEye(
    frame: SensoryFrame,
    flyX: number,
    flyY: number,
    heading: number,
    eye: Eye,
  ): { px: [number, number] | null; r: number } {
    const [cx, cy] = Senses.eyeCentre(flyX, flyY, heading, eye);
    const relX = frame.cursorX - cx;
    const relY = frame.cursorY - cy;
    if (Math.abs(relX) > EYE_RADIUS * 1.3 || Math.abs(relY) > EYE_RADIUS * 1.3) {
      return { px: null, r: 0 };
    }
    const scale = PATCH / (2 * EYE_RADIUS);
    const dist = Math.hypot(frame.cursorX - flyX, frame.cursorY - flyY);
    const rScreen = Math.min(70.0, 2600.0 / Math.max(dist, 30.0));
    return {
      px: [(relX + EYE_RADIUS) * scale, (relY + EYE_RADIUS) * scale],
      r: rScreen * scale,
    };
  }

  /**
   * `t` is **simulated** seconds — the approach speed below is a
   * derivative, and mixing wall time into it would make the fly more or
   * less alarmed depending on how fast the machine happens to be.
   */
  sense(
    frame: SensoryFrame,
    flyX: number,
    flyY: number,
    heading: number,
    t: number,
  ): SensedWorld {
    const dx = frame.cursorX - flyX;
    const dy = frame.cursorY - flyY;
    const dist = Math.hypot(dx, dy);

    const dt = Math.max(1e-3, t - this.lastT);
    const approach = this.lastT ? (this.lastDist - dist) / dt : 0;
    this.lastDist = dist;
    this.lastT = t;

    let threat = 0;
    if (dist < this.loomRadius) {
      const prox = 1.0 - dist / this.loomRadius;
      threat = prox * prox;
      if (approach > 0) {
        threat += prox * Math.min(1.0, (this.approachGain * approach) / 100.0);
      }
      if (dist < this.panicRadius) threat = Math.max(threat, 0.85);
    }
    threat = Math.min(1.0, threat);

    const bearing = Math.atan2(dy, dx);
    // Screen y grows downward, so a negative sine puts the cursor on the
    // fly's left.
    const leftSide = Math.sin(bearing - heading) < 0;

    const channels: RateChannel[] = [];
    if (this.retina) {
      for (const [eye, patch] of [
        ["L", frame.patchL],
        ["R", frame.patchR],
      ] as const) {
        const { px, r } = this.cursorInEye(frame, flyX, flyY, heading, eye);
        channels.push(...this.retina.process(eye, patch, px, r, frame.patchDt));
      }
    }

    const pops: { pop: string; rate: number }[] = [];
    const loom = this.loomRateMax * threat * this.loomInjection;
    if (loom > 0) {
      const near = loom;
      const far = loom * 0.15;
      pops.push(
        { pop: "LC4_L", rate: leftSide ? near : far },
        { pop: "LC4_R", rate: leftSide ? far : near },
        { pop: "LPLC2_L", rate: leftSide ? near : far },
        { pop: "LPLC2_R", rate: leftSide ? far : near },
      );
    }

    return { channels, pops, threat, bearing };
  }
}
