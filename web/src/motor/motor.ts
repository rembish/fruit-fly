/**
 * Descending neurons -> flight across a canvas.
 *
 * Port of `fruitfly/motor.py`, constants included and unchanged. This is
 * the least principled part of the whole project and the README says so:
 * the wing motor neurons live in the ventral nerve cord and this
 * connectome stops at the neck, so turning descending rates into 2D
 * motion is ours. What it is *not* is arbitrary — every number below was
 * tuned against a captured 120 s descending trace, and M0.2's pad
 * statistics were measured through this exact state machine.
 *
 * The grounding, neuron by neuron:
 *
 *   GF (DNp01)        escape. It fires sporadically at rest, so the
 *                     readout thresholds its *rate*: lone spikes are
 *                     jinks, a sustained burst is a directed escape.
 *   DNa02 left/right  steering, by rate asymmetry — DNa02 drives turns
 *                     toward its own side.
 *   DNp09             forward drive.
 *   MDN               backward drive (the moonwalker neurons).
 *   descending pool   arousal: whether the fly flies at all.
 */

import { Rng } from "../brain/rng.js";

export const FLYING = "flying";
export const LANDED = "landed";
export const ESCAPE = "escape";
export const SQUASHED = "squashed";
/** Startled: wings up, feet still down — and squashable. */
export const TAKEOFF = "takeoff";

export type MotorPhase =
  | typeof FLYING
  | typeof LANDED
  | typeof ESCAPE
  | typeof SQUASHED
  | typeof TAKEOFF;

/** How long the remains stay on screen. */
export const SPLAT_S = 4.0;

export interface MotorState {
  x: number;
  y: number;
  /** Radians, screen coordinates (y down). */
  heading: number;
  /** Pixels per second. */
  speed: number;
  state: MotorPhase;
  wingPhase: number;
  /** Human-readable, for the HUD. */
  lastEvent: string;
}

/** The rate dict the brain thread posts back. */
export type Rates = Record<string, number>;

export class MotorMap {
  // Idle GF hums at ~6 Hz in clustered doublets; looming drives ~50 Hz
  // sustained. A slow rate estimate plus a high threshold separates them.
  static readonly ESCAPE_GF_HZ = 30.0;
  static readonly GF_TAU = 0.3; // s
  static readonly ESCAPE_REFRACT = 0.7; // s
  static readonly JINK_COOLDOWN = 1.2; // s
  // Fly/land balance, tuned against a captured trace whose pool
  // percentiles were p10/50/90 = 3.9/5.1/7.0 Hz. Real flies spend most of
  // their time sitting; these give ~70% ground time undisturbed.
  static readonly LAND_REF = 6.3; // Hz
  static readonly LAND_THRESH: readonly [number, number] = [0.6, 2.0];
  static readonly TAKEOFF_REF = 8.8; // Hz
  static readonly TAKEOFF_THRESH: readonly [number, number] = [2.5, 6.0];
  // A hunted fly is reluctant to land, not incapable. Threat scales the
  // calm accumulation down rather than zeroing it — zeroing meant a fly
  // with the cursor anywhere near it could never land at all, which
  // measured as 0% ground time while hovering.
  static readonly THREAT_LAND_GATE = 1.0;

  readonly st: MotorState;
  private readonly rng: Rng;

  private escapeUntil = 0;
  private escapeDir = 0;
  private takeoffDrive = 0;
  private landDrive = 0;
  private landThresh = 2.0;
  private gfRate = 0;
  private lastJink = -10.0;
  private squashT = 0;
  private takeoffUntil = 0;
  private escapeOnTakeoff = false;

  constructor(
    readonly w: number,
    readonly h: number,
    seed = 4,
  ) {
    this.rng = new Rng(seed);
    this.st = {
      x: w * 0.5,
      y: h * 0.4,
      heading: 0,
      speed: 0,
      state: LANDED,
      wingPhase: 0,
      lastEvent: "",
    };
  }

  /**
   * Begin takeoff. A real fly needs ~100-200 ms to get airborne after its
   * escape circuit fires, and it can be swatted throughout — that latency
   * is the entire reason flyswatters work, so it is modelled rather than
   * skipped.
   */
  private startle(t: number, event: string, escape: boolean): void {
    this.st.state = TAKEOFF;
    this.st.speed = 0;
    this.st.lastEvent = event;
    this.takeoffUntil = t + this.rng.uniform(0.1, 0.22);
    this.escapeOnTakeoff = escape;
  }

  /** A swat landed on a sitting fly. It is over. */
  squash(t: number): void {
    this.st.state = SQUASHED;
    this.st.speed = 0;
    this.st.lastEvent = "SPLAT.";
    this.squashT = t;
  }

  /** A swat clipped a flying fly: tumble and bolt. */
  glancingBlow(t: number): void {
    this.st.state = ESCAPE;
    this.st.lastEvent = "glancing blow -> tumbling away";
    this.escapeUntil = t + 0.3;
    this.escapeDir = this.rng.uniform(0, 2 * Math.PI);
  }

  private respawn(): void {
    const st = this.st;
    const m = 30.0;
    switch (this.rng.below(4)) {
      case 0:
        st.x = m;
        st.y = this.rng.uniform(m, this.h - m);
        break;
      case 1:
        st.x = this.w - m;
        st.y = this.rng.uniform(m, this.h - m);
        break;
      case 2:
        st.x = this.rng.uniform(m, this.w - m);
        st.y = m;
        break;
      default:
        st.x = this.rng.uniform(m, this.w - m);
        st.y = this.h - m;
    }
    st.heading =
      Math.atan2(this.h / 2 - st.y, this.w / 2 - st.x) +
      this.rng.uniform(-0.5, 0.5);
    st.state = FLYING;
    st.speed = 320.0;
    st.lastEvent = "another fly got in through the window";
    this.gfRate = 0;
    this.takeoffDrive = 0;
    this.landDrive = 0;
  }

  /**
   * Advance the body by `dt` **simulated** seconds, at simulated time `t`.
   *
   * Never wall time. The whole sim-clock design rests on this: the brain
   * sets the pace, the body follows it, and on a slow machine everything
   * enters slow motion together rather than the motor tuning coming apart.
   */
  update(
    dt: number,
    t: number,
    rates: Rates,
    gfCount: number,
    threatBearing: number,
    threat: number,
  ): MotorState {
    const st = this.st;

    if (st.state === SQUASHED) {
      if (t - this.squashT > SPLAT_S) this.respawn();
      return st;
    }

    // --- giant fiber: jinks on lone spikes, escape on sustained bursts ---
    this.gfRate +=
      (gfCount / Math.max(dt, 1e-3) - this.gfRate) *
      Math.min(1.0, dt / MotorMap.GF_TAU);

    if (
      this.gfRate > MotorMap.ESCAPE_GF_HZ &&
      st.state !== ESCAPE &&
      t - this.escapeUntil > MotorMap.ESCAPE_REFRACT
    ) {
      this.gfRate = 0;
      this.escapeDir =
        threat > 0.05
          ? threatBearing + Math.PI + this.rng.uniform(-0.7, 0.7)
          : this.rng.uniform(0, 2 * Math.PI);
      if (st.state === LANDED) {
        this.startle(t, "giant fiber burst -> scrambling to take off!", true);
      } else if (st.state === TAKEOFF) {
        this.escapeOnTakeoff = true;
      } else {
        st.state = ESCAPE;
        st.lastEvent = "giant fiber burst -> ESCAPE!";
        this.escapeUntil = t + 0.22;
      }
    } else if (
      gfCount &&
      st.state === FLYING &&
      t - this.lastJink > MotorMap.JINK_COOLDOWN
    ) {
      st.heading += this.rng.sign() * this.rng.uniform(0.6, 1.4);
      st.speed += 180.0;
      st.lastEvent = "giant fiber spike -> jink";
      this.lastJink = t;
    } else if (
      gfCount &&
      st.state === LANDED &&
      threat < 0.05 &&
      t - this.lastJink > MotorMap.JINK_COOLDOWN
    ) {
      // Startle hop in place: reposition slightly, stay on the ground.
      const ang = this.rng.uniform(0, 2 * Math.PI);
      st.x += Math.cos(ang) * 14.0;
      st.y += Math.sin(ang) * 14.0;
      st.heading = this.rng.uniform(0, 2 * Math.PI);
      st.lastEvent = "giant fiber spike -> startle hop";
      this.lastJink = t;
    }

    const dnaL = rates["DNa02_L"] ?? 0;
    const dnaR = rates["DNa02_R"] ?? 0;
    const desc = rates["descending"] ?? 0;
    const fwd = rates["DNp09"] ?? 0;
    const back = rates["MDN"] ?? 0;

    if (st.state === TAKEOFF) {
      st.speed = 0;
      st.wingPhase += dt * 200.0 * 2 * Math.PI; // revving up
      if (t > this.takeoffUntil) {
        if (this.escapeOnTakeoff) {
          st.state = ESCAPE;
          this.escapeUntil = t + 0.22;
          st.heading = this.escapeDir;
        } else {
          st.state = FLYING;
          st.heading = this.rng.uniform(0, 2 * Math.PI);
        }
        st.speed = 260.0;
      }
    } else if (st.state === ESCAPE) {
      st.heading = this.escapeDir;
      st.speed = 1400.0;
      if (t > this.escapeUntil) {
        st.state = FLYING;
        st.speed = 500.0;
      }
    } else if (st.state === FLYING) {
      // Steering: DNa02 asymmetry drives ipsilateral turns. The scales
      // match the tuned brain — DNa02 idles 5-15 Hz per side and bursts
      // past 40; the descending pool idles 3-6 Hz.
      const turn = (dnaR - dnaL) * 0.12;
      st.heading += Math.max(-5.0, Math.min(5.0, turn)) * dt;

      const pSaccade = Math.min(0.9, Math.max(0, desc - 4.0) * 0.1) * dt * 10;
      if (this.rng.next() < pSaccade) {
        st.heading += this.rng.sign() * this.rng.uniform(0.5, 1.6);
        st.lastEvent = "descending burst -> saccade";
      }

      let target =
        90.0 +
        45.0 * Math.min(10.0, desc) +
        60.0 * Math.min(5.0, fwd) -
        40.0 * Math.min(5.0, back);
      target = Math.max(60.0, target);
      st.speed += (target - st.speed) * Math.min(1.0, 5.0 * dt);

      // Landing drive: a leaky accumulator of calm. It grows while the
      // descending pool sits below its median, drains when aroused, and
      // lands when it wins — which gives naturally variable flight bouts
      // without needing unbroken quiet.
      let calm = Math.max(-1.0, Math.min(1.0, MotorMap.LAND_REF - desc));
      if (calm > 0) {
        const gate = MotorMap.THREAT_LAND_GATE;
        calm =
          gate <= 0
            ? threat > 0.05
              ? 0
              : calm
            : calm * Math.max(0, 1.0 - threat / gate);
      }
      this.landDrive = Math.max(0, this.landDrive + calm * dt);
      if (this.landDrive > this.landThresh) {
        st.state = LANDED;
        st.speed = 0;
        st.lastEvent = "descending activity low -> landing";
        this.landDrive = 0;
      }
    } else {
      // LANDED: sitting, until the brain stirs.
      st.speed = 0;
      this.takeoffDrive +=
        Math.max(0, desc - MotorMap.TAKEOFF_REF + fwd) * dt;
      this.takeoffDrive *= 1.0 - 0.1 * dt;
      if (threat > 0.5) {
        this.escapeDir = threatBearing + Math.PI + this.rng.uniform(-0.7, 0.7);
        this.startle(t, "looming! -> scrambling to take off", true);
        this.takeoffDrive = 0;
        this.landDrive = 0;
        this.landThresh = this.rng.uniform(...MotorMap.LAND_THRESH);
      } else if (
        this.takeoffDrive > this.rng.uniform(...MotorMap.TAKEOFF_THRESH)
      ) {
        this.startle(t, "descending activity -> takeoff", false);
        this.takeoffDrive = 0;
        this.landDrive = 0;
        this.landThresh = this.rng.uniform(...MotorMap.LAND_THRESH);
      }
    }

    if (st.speed > 0) {
      st.x += Math.cos(st.heading) * st.speed * dt;
      st.y += Math.sin(st.heading) * st.speed * dt;
      st.wingPhase += dt * 200.0 * 2 * Math.PI; // ~200 Hz wingbeat
    }

    // Keep on the canvas: turn away from the edges like a fly in a bottle.
    // The 24 px margin is absolute, which is why M0.2 pinned its numbers
    // to a 960x540 field — on a bigger one the fly sits in the middle of
    // a larger empty area and the pad statistics move.
    const margin = 24.0;
    let bounced = false;
    if (st.x < margin) {
      st.x = margin;
      bounced = true;
    } else if (st.x > this.w - margin) {
      st.x = this.w - margin;
      bounced = true;
    }
    if (st.y < margin) {
      st.y = margin;
      bounced = true;
    } else if (st.y > this.h - margin) {
      st.y = this.h - margin;
      bounced = true;
    }
    if (bounced && st.speed > 0) {
      st.heading =
        Math.atan2(this.h / 2 - st.y, this.w / 2 - st.x) +
        this.rng.uniform(-0.6, 0.6);
    }

    return st;
  }
}
