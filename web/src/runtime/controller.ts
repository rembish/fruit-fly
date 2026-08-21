/**
 * The main thread: body, world, retina sampling, screen.
 *
 * Mirrors the desktop's `Controller`. The differences are the ones the
 * browser forces and one it does not:
 *
 *   The world renders to an **offscreen** canvas and the retina samples
 *   *that*. The visible canvas is the world with the fly composited on
 *   top, so the fly cannot see itself — the same principle as the
 *   desktop's capture exclusion, and here it costs nothing but a second
 *   canvas. A fly that sees itself sees a looming object that follows it
 *   everywhere.
 *
 *   The cursor is not in those pixels either. It enters the retina
 *   through `cursorInEye`, with the angular size that a flat screen
 *   cannot supply on its own. That is the sabotage the desktop version
 *   is built around and the plan keeps it: the spectator is a threat.
 *
 *   Everything advances on the SimClock, never on rAF's wall clock. The
 *   frame loop's only job is to ask what time it is *for the fly* and
 *   draw the answer.
 */

import { MotorMap, ESCAPE, FLYING, SQUASHED, TAKEOFF, LANDED } from "../motor/motor.js";
import { PressDetector } from "../motor/pads.js";
import { EYE_RADIUS, PATCH } from "../senses/retina.js";
import { Senses } from "../senses/senses.js";
import { drawFly, drawSplat } from "../ui/sprite.js";
import { SimClock } from "./simclock.js";
import type { Game } from "../games/api.js";
import type { FromWorker, SenseMessage, ToWorker } from "./protocol.js";

/**
 * The play field, and not a free choice.
 *
 * M0.2 measured the fly's occupancy and every pad's press rate at this
 * size, and the motor map speaks absolute pixels — a 24 px edge margin,
 * a 260-500 px/s cruise, a 1400 px/s escape. On a larger field the fly
 * crosses less of it per second and sits in the middle of a bigger empty
 * area, so the pad statistics move. Phase 3 builds here or re-measures.
 */
export const CANVAS_W = 960;
export const CANVAS_H = 540;

/** Sensory ticks per simulated second. The desktop samples at ~20 Hz. */
const SENSE_HZ = 20;

export interface Hud {
  simSpeed: number;
  spikesPerSecond: number;
  threat: number;
  state: string;
  lastEvent: string;
  rates: Record<string, number>;
  simSeconds: number;
}

export class Controller {
  readonly motor = new MotorMap(CANVAS_W, CANVAS_H);
  readonly clock = new SimClock();

  /** The retina's source: the world alone, with no fly and no cursor. */
  readonly world: HTMLCanvasElement;
  private readonly worldCtx: CanvasRenderingContext2D;
  private readonly viewCtx: CanvasRenderingContext2D;

  private cursorX = -1e9;
  private cursorY = -1e9;
  private threat = 0;
  private bearing = 0;
  private rates: Record<string, number> = {};
  private gfCount = 0;
  private simSpeed = 0;
  private spikesPerSecond = 0;

  private nextSenseAt = 0;
  private lastSenseSim = 0;
  private lastEvent = "";

  /** Called whenever the fly's own narration changes. */
  onEvent: ((text: string) => void) | null = null;

  /** Optional cabinet. Without one this is just a fly on a canvas. */
  game: Game | null = null;
  private readonly presses = new PressDetector();

  constructor(
    private readonly view: HTMLCanvasElement,
    private readonly worker: Worker,
    private readonly drawWorld: (ctx: CanvasRenderingContext2D, t: number) => void,
  ) {
    view.width = CANVAS_W;
    view.height = CANVAS_H;
    this.world = document.createElement("canvas");
    this.world.width = CANVAS_W;
    this.world.height = CANVAS_H;
    const wc = this.world.getContext("2d", { willReadFrequently: true });
    const vc = view.getContext("2d");
    if (!wc || !vc) throw new Error("canvas 2d context unavailable");
    this.worldCtx = wc;
    this.viewCtx = vc;

    // addEventListener rather than onmessage: the page listens for load
    // progress on the same worker, and a second `onmessage =` would
    // silently unhook this one.
    worker.addEventListener("message", (ev: MessageEvent<FromWorker>) =>
      this.onWorker(ev.data),
    );
    view.addEventListener("pointermove", (e) => {
      const r = view.getBoundingClientRect();
      this.cursorX = ((e.clientX - r.left) / r.width) * CANVAS_W;
      this.cursorY = ((e.clientY - r.top) / r.height) * CANVAS_H;
    });
    view.addEventListener("pointerleave", () => {
      this.cursorX = -1e9;
      this.cursorY = -1e9;
    });
    view.addEventListener("pointerdown", () => this.onSwat());
  }

  private onWorker(msg: FromWorker): void {
    if (msg.kind !== "tick") return;
    this.rates = msg.rates;
    this.gfCount += msg.gfCount;
    this.threat = msg.threat;
    this.bearing = msg.bearing;
    this.simSpeed = msg.simSpeed;
    this.spikesPerSecond = msg.spikesPerSecond;
    this.clock.advanceTo(msg.simTimeMs);
  }

  private send(msg: ToWorker, transfer: Transferable[] = []): void {
    this.worker.postMessage(msg, transfer);
  }

  poke(pop: string, hz = 120, seconds = 0.4): void {
    this.send({ kind: "poke", pop, hz, seconds });
  }

  private onSwat(): void {
    const st = this.motor.st;
    const t = this.clock.seconds;
    if (st.state === SQUASHED) return;
    const dist = Math.hypot(this.cursorX - st.x, this.cursorY - st.y);
    if (dist > 22) return;
    if (st.state === LANDED || st.state === TAKEOFF) {
      // Caught on the ground, or mid-startle with its wings up and its
      // feet still down. That window is why flyswatters work.
      this.motor.squash(t);
      this.send({ kind: "control", reset: true });
    } else {
      this.motor.glancingBlow(t);
      this.send({ kind: "poke", pop: "JO", hz: 150, seconds: 0.25 });
    }
  }

  /**
   * Sample one eye out of the world canvas.
   *
   * `getImageData` is the expensive call in the frame, which is why this
   * runs at ~20 Hz of *simulated* time rather than every repaint. A
   * fresh Float32Array each time so it can be transferred to the worker
   * rather than copied; at 73 KB per sample there is nothing to pool.
   */
  private samplePatch(eye: "L" | "R"): Float32Array {
    const st = this.motor.st;
    const [cx, cy] = Senses.eyeCentre(st.x, st.y, st.heading, eye);
    const side = Math.round(2 * EYE_RADIUS);
    const sx = Math.max(0, Math.min(CANVAS_W - side, Math.round(cx - EYE_RADIUS)));
    const sy = Math.max(0, Math.min(CANVAS_H - side, Math.round(cy - EYE_RADIUS)));
    const img = this.worldCtx.getImageData(sx, sy, side, side);
    const out = new Float32Array(PATCH * PATCH);
    const step = side / PATCH;
    for (let py = 0; py < PATCH; py++) {
      const srcY = Math.min(side - 1, Math.floor(py * step));
      for (let px = 0; px < PATCH; px++) {
        const srcX = Math.min(side - 1, Math.floor(px * step));
        const o = (srcY * side + srcX) * 4;
        // Rec. 601 luma, the same weighting the desktop's grab uses.
        out[py * PATCH + px] =
          (0.299 * img.data[o]! +
            0.587 * img.data[o + 1]! +
            0.114 * img.data[o + 2]!) /
          255;
      }
    }
    return out;
  }

  private sense(simSeconds: number): void {
    const st = this.motor.st;
    const patchL = this.samplePatch("L");
    const patchR = this.samplePatch("R");
    const msg: SenseMessage = {
      kind: "sense",
      patchL,
      patchR,
      patchDt: Math.min(0.5, simSeconds - this.lastSenseSim),
      flyX: st.x,
      flyY: st.y,
      heading: st.heading,
      cursorX: this.cursorX,
      cursorY: this.cursorY,
    };
    this.lastSenseSim = simSeconds;
    this.send(msg, [patchL.buffer, patchR.buffer]);
  }

  /** One display frame. Called from rAF, but paced by the fly's clock. */
  frame(): void {
    const dt = this.clock.take();
    const t = this.clock.seconds;

    if (dt > 0) {
      const prev = this.motor.st.lastEvent;
      this.motor.update(dt, t, this.rates, this.gfCount, this.bearing, this.threat);
      this.gfCount = 0;
      if (this.motor.st.lastEvent !== prev) {
        this.lastEvent = this.motor.st.lastEvent;
        this.onEvent?.(this.lastEvent);
      }
    }

    // The game runs on the fly's clock, and it is told what the fly did
    // rather than being allowed to ask for anything. Press detection is
    // the runtime's, not the game's: it is the one piece of logic M0.2
    // decided and no cabinet may reinterpret it.
    if (this.game && dt > 0) {
      const pressed = this.presses.poll(
        this.game.pads(),
        this.motor.st,
        CANVAS_W,
        CANVAS_H,
      );
      this.game.tick({ dt, t, fly: this.motor.st, pressed });
    }

    // The world is redrawn every frame so the retina always samples the
    // current scene, even on a frame the fly did not move.
    if (this.game) this.game.drawWorld(this.worldCtx, CANVAS_W, CANVAS_H);
    else this.drawWorld(this.worldCtx, t);

    if (this.clock.running && t >= this.nextSenseAt) {
      this.nextSenseAt = t + 1 / SENSE_HZ;
      this.sense(t);
    }

    // Composite: world, then the fly. Nothing the fly can see includes
    // the fly.
    this.viewCtx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    this.viewCtx.drawImage(this.world, 0, 0);
    const st = this.motor.st;
    if (st.state === SQUASHED) {
      drawSplat(this.viewCtx, st.x, st.y, st.heading, 34);
    } else {
      drawFly(this.viewCtx, st.x, st.y, {
        size: 34,
        heading: st.heading,
        flying: st.state === FLYING || st.state === ESCAPE || st.state === TAKEOFF,
        escaping: st.state === ESCAPE || st.state === TAKEOFF,
        wingPhase: st.wingPhase,
      });
    }
    // Scoreboards and captions go on last and only here: the fly should
    // not be reading its own score out of its own retina.
    this.game?.drawOverlay?.(this.viewCtx, CANVAS_W, CANVAS_H);
  }

  /** Swap cabinets without restarting the brain. */
  setGame(game: Game | null): void {
    this.game = game;
    this.presses.reset();
  }

  hud(): Hud {
    return {
      simSpeed: this.simSpeed,
      spikesPerSecond: this.spikesPerSecond,
      threat: this.threat,
      state: this.motor.st.state,
      lastEvent: this.lastEvent,
      rates: this.rates,
      simSeconds: this.clock.seconds,
    };
  }
}
