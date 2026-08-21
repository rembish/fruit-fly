/**
 * What a cabinet is.
 *
 * The runtime owns the fly, the pads and the press detection; a game
 * owns its own world and score and nothing else. That split is what
 * lets Pong and Tetris arrive later as pure additions — the fly does
 * not know which game it is playing, and no game may reach into the
 * fly.
 *
 * Everything is driven in **simulated** seconds. A game that reached for
 * a wall clock would come apart the moment the brain fell behind
 * realtime, which it does on most machines.
 */

import type { Pad, PadSensor } from "../motor/pads.js";
import type { MotorState } from "../motor/motor.js";

/** What the runtime tells a game about the fly, once per frame. */
export interface GameContext {
  /** Simulated seconds since the previous tick. */
  dt: number;
  /** Simulated seconds since the round began. */
  t: number;
  /** The fly, read-only. Games observe; they never steer. */
  fly: Readonly<MotorState>;
  /** Pads the fly newly arrived on this frame. */
  pressed: readonly Pad[];
}

export interface Game {
  readonly id: string;
  readonly name: string;
  /** One line for the cabinet, in the fly's favour or not. */
  readonly blurb: string;
  /** Pads the runtime should watch and draw. */
  pads(): readonly Pad[];
  /**
   * Where the fly is allowed to be, in canvas fractions, or null for the
   * whole field.
   *
   * A game may keep the fly in a chamber rather than let it roam over
   * the playfield — which is what an input device physically is. It also
   * invalidates every press statistic measured on the full canvas, so a
   * game that uses this owes its own measurement.
   */
  flyBounds?(): readonly [number, number, number, number] | null;
  /**
   * How this game's pads decide they are pressed. Defaults to M0.2's
   * rule, which is the honest one; a game may ask for the easier switch
   * and owes an explanation on the page if it does.
   */
  padSensor?(): PadSensor;
  /**
   * Simulated seconds between repeats while a pad stays pressed, or 0
   * for a pure edge trigger.
   */
  padRepeat?(): number;
  /** Fresh round. */
  reset(): void;
  tick(ctx: GameContext): void;
  /**
   * Draw the world the retina will sample.
   *
   * The design doc is explicit that the game belongs here rather than on
   * a separate layer: "the game is rendered where the retina samples, so
   * the pipes loom in the fly's real optic lobe". What that costs is
   * measured rather than assumed — see the vision note in the changelog.
   */
  drawWorld(ctx: CanvasRenderingContext2D, w: number, h: number): void;
  /** Overlay drawn on the visible canvas only: never seen by the fly. */
  drawOverlay?(ctx: CanvasRenderingContext2D, w: number, h: number): void;
  readonly score: number;
  readonly best: number;
  readonly over: boolean;
}

const registry = new Map<string, () => Game>();

export function register(id: string, make: () => Game): void {
  registry.set(id, make);
}

export function create(id: string): Game {
  const make = registry.get(id);
  if (!make) throw new Error(`no game registered as ${id}`);
  return make();
}

export function catalogue(): string[] {
  return [...registry.keys()];
}
