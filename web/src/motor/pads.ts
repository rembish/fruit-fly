/**
 * Pads, and what counts as pressing one.
 *
 * The rule is M0.2's, measured rather than chosen. Two findings from that
 * experiment are baked in here and neither is negotiable without
 * re-measuring:
 *
 *   A press is an **arrival**, not a dwell. It fires on the rising edge
 *   of "on the pad and landed"; a fly that sits there for four seconds
 *   has pressed once, not two hundred and forty times.
 *
 *   The predicate is **landed-only**. M0.2 swept three definitions of
 *   "slow" and every candidate pad gave an identical press rate across
 *   all of them: every press was a landing, so the speed clause earned
 *   nothing and is not here. A 1400 px/s escape dart crossing a pad is a
 *   startle, not a decision, and must not chord the game.
 *
 * Geometry is in canvas fractions so one set of numbers survives a resize
 * — although M0.2's *rates* do not, because the motor map speaks absolute
 * pixels. That is why the play field is pinned to 960x540.
 */

import { LANDED, type MotorState } from "./motor.js";

export interface Pad {
  id: string;
  label: string;
  /** Fractions of the canvas: [x0, y0, x1, y1]. */
  rect: readonly [number, number, number, number];
}

/**
 * The FLAP pad M0.2 chose: full width, bottom 20%.
 *
 * Not the bottom 10% — that measured *zero* presses in two minutes,
 * because edge avoidance turns the fly back before it reaches the floor.
 * Not the middle 60% either, which lost a quarter of the presses. This
 * one gets hit about four times a minute.
 */
export const FLAP_PAD: Pad = {
  id: "flap",
  label: "FLAP",
  rect: [0.0, 0.8, 1.0, 1.0],
};

export function padPixels(
  pad: Pad,
  width: number,
  height: number,
): { x: number; y: number; w: number; h: number } {
  const [x0, y0, x1, y1] = pad.rect;
  return {
    x: x0 * width,
    y: y0 * height,
    w: (x1 - x0) * width,
    h: (y1 - y0) * height,
  };
}

export function onPad(
  pad: Pad,
  st: Pick<MotorState, "x" | "y">,
  width: number,
  height: number,
): boolean {
  const [x0, y0, x1, y1] = pad.rect;
  return (
    st.x >= x0 * width &&
    st.x <= x1 * width &&
    st.y >= y0 * height &&
    st.y <= y1 * height
  );
}

/** Is the fly currently eligible to be pressing this pad? */
export function padEligible(
  pad: Pad,
  st: Pick<MotorState, "x" | "y" | "state">,
  width: number,
  height: number,
): boolean {
  return st.state === LANDED && onPad(pad, st, width, height);
}

/**
 * Edge-triggered press detection.
 *
 * Holds one boolean per pad — whether the fly was eligible last frame —
 * and reports only the transitions into eligibility. Stateful on purpose:
 * "press" is a property of the *sequence*, and no snapshot of the fly can
 * answer it.
 */
export class PressDetector {
  private readonly was = new Map<string, boolean>();

  /** Pads newly arrived on this frame, in registration order. */
  poll(
    pads: readonly Pad[],
    st: Pick<MotorState, "x" | "y" | "state">,
    width: number,
    height: number,
  ): Pad[] {
    const pressed: Pad[] = [];
    for (const pad of pads) {
      const now = padEligible(pad, st, width, height);
      if (now && !this.was.get(pad.id)) pressed.push(pad);
      this.was.set(pad.id, now);
    }
    return pressed;
  }

  /** Forget the history — for a restart, where arrival should count again. */
  reset(): void {
    this.was.clear();
  }
}
