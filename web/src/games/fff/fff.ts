/**
 * Fruit Flappy Fly, in two modes, because they are two different claims.
 *
 * **controller** — the design doc's game, and the joke it was built
 * around. A bird falls under gravity and flaps when, and only when, the
 * fly lands on the FLAP pad at the bottom of the play field. The fly is
 * an input device. It has no idea a game is happening; it is a fly. The
 * headline the doc wants is not "a fly plays Flappy Bird" — it is "a
 * fruit fly's connectome scores no better than chance at Flappy Bird,
 * and here is the measurement", which is why the flapper is swappable:
 * the fly, a Poisson process rate-matched to the fly's own press rate,
 * or nothing at all.
 *
 * **pilot** — the fly *is* the bird. No pad, no bird sprite: the pipes
 * come at the fly and its own body has to be in the gap. Nothing steers
 * it toward the gap, so this is not a game it can win; it is a way of
 * watching what a connectome does when a wall arrives, which M0.3
 * measured at the population level and this shows at the whole-animal
 * one.
 *
 * Both render the game into the world canvas the retina samples, as the
 * doc requires: "the game is rendered where the retina samples, so the
 * pipes loom in the fly's real optic lobe". In controller mode that is a
 * genuine confound as well as a feature — Phase 2 measured the
 * descending pool swinging 3.2-12.2 Hz with the eyes open on a moving
 * scene, which moves the fly's landing behaviour and therefore its press
 * rate. The Poisson arm does not have that coupling, so the comparison
 * has to be read with it in mind. `--no-scene` exists for exactly that.
 */

import type { Game, GameContext } from "../api.js";
import { FLAP_PAD, padPixels, type Pad } from "../../motor/pads.js";
import { PipeField } from "./pipes.js";

export type FffMode = "controller" | "pilot";
/** Who supplies the flaps in controller mode. */
export type Flapper = "fly" | "poisson" | "nobody";

export interface FffOptions {
  width: number;
  height: number;
  mode?: FffMode;
  flapper?: Flapper;
  /**
   * Render the pipes into the retina's canvas.
   *
   * On by default because the doc asks for it. Turning it off is the
   * control condition for the confound above: the same fly, the same
   * pad, a scene it cannot see.
   */
  scene?: boolean;
  seed?: number;
}

/** Bird physics, in pixels and simulated seconds. */
const GRAVITY = 1150;
const FLAP_IMPULSE = -390;
const MAX_FALL = 620;
const BIRD_X = 240;
const BIRD_R = 13;

export class Fff implements Game {
  readonly id = "fff";
  readonly name = "Fruit Flappy Fly";

  mode: FffMode;
  flapper: Flapper;
  scene: boolean;

  private readonly w: number;
  private readonly h: number;
  private field: PipeField;

  // Controller mode only.
  private birdY = 0;
  private birdV = 0;
  private flapFlash = 0;

  private roundT = 0;
  private deadFor = 0;
  private rng: number;

  /** Presses seen, so the Poisson arm can be rate-matched to the fly. */
  pressCount = 0;
  private pressWindowT = 0;

  score = 0;
  best = 0;
  over = false;
  /** Simulated seconds the current round has survived. */
  survived = 0;
  /** Longest round this session, in simulated seconds. */
  bestSurvived = 0;

  constructor(opts: FffOptions) {
    this.w = opts.width;
    this.h = opts.height;
    this.mode = opts.mode ?? "controller";
    this.flapper = opts.flapper ?? "fly";
    this.scene = opts.scene ?? true;
    this.rng = (opts.seed ?? 99) >>> 0;
    this.field = new PipeField({ width: this.w, height: this.h }, opts.seed);
    this.reset();
  }

  get blurb(): string {
    return this.mode === "controller"
      ? "the fly lands on a pad; the pad flaps a bird"
      : "the fly is the bird, and nothing is aiming it";
  }

  private rand(): number {
    let x = this.rng;
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    this.rng = x >>> 0;
    return this.rng / 4294967296;
  }

  pads(): readonly Pad[] {
    // No pad in pilot mode: there is nothing to press, the fly *is* the
    // player, and drawing one would promise a mechanism that is absent.
    return this.mode === "controller" ? [FLAP_PAD] : [];
  }

  reset(): void {
    this.field.reset();
    this.birdY = this.h * 0.4;
    this.birdV = 0;
    this.score = 0;
    this.over = false;
    this.roundT = 0;
    this.deadFor = 0;
    this.survived = 0;
    this.flapFlash = 0;
  }

  setMode(mode: FffMode): void {
    this.mode = mode;
    this.bestSurvived = 0;
    this.best = 0;
    this.reset();
  }

  private flap(): void {
    this.birdV = FLAP_IMPULSE;
    this.flapFlash = 0.14;
  }

  tick(ctx: GameContext): void {
    const { dt } = ctx;
    this.roundT += dt;
    this.flapFlash = Math.max(0, this.flapFlash - dt);

    if (this.over) {
      // A short beat on the wreck, then straight back in. Rounds are
      // about three seconds; a menu would be longer than the game.
      this.deadFor += dt;
      if (this.deadFor > 1.2) this.reset();
      return;
    }

    this.survived += dt;
    this.pressWindowT += dt;
    if (ctx.pressed.length) this.pressCount += ctx.pressed.length;

    if (this.mode === "controller") {
      let flapped = ctx.pressed.some((p) => p.id === FLAP_PAD.id);
      if (this.flapper === "poisson") {
        // Rate-matched to the fly's own presses so far, which is the
        // only fair version of this comparison. Before the fly has
        // pressed anything there is no rate to match, so the arm holds
        // still rather than inventing one.
        const rate = this.pressWindowT > 0 ? this.pressCount / this.pressWindowT : 0;
        flapped = this.rand() < rate * dt;
      } else if (this.flapper === "nobody") {
        flapped = false;
      }
      if (flapped) this.flap();

      this.birdV = Math.min(MAX_FALL, this.birdV + GRAVITY * dt);
      this.birdY += this.birdV * dt;

      this.score += this.field.advance(dt, BIRD_X);
      const hitGround = this.birdY + BIRD_R > this.h || this.birdY - BIRD_R < 0;
      if (hitGround || this.field.hits(BIRD_X, this.birdY, BIRD_R)) this.die();
    } else {
      // Pilot: the fly's own body is the player. Nothing here moves it —
      // the motor map does, out of descending drive, and the pipes are
      // simply in the way.
      this.score += this.field.advance(dt, ctx.fly.x);
      if (this.field.hits(ctx.fly.x, ctx.fly.y, 12)) this.die();
    }
  }

  private die(): void {
    this.over = true;
    this.deadFor = 0;
    this.best = Math.max(this.best, this.score);
    this.bestSurvived = Math.max(this.bestSurvived, this.survived);
  }

  drawWorld(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, "#1a2433");
    sky.addColorStop(0.75, "#243247");
    sky.addColorStop(1, "#141a24");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);

    if (this.scene) {
      this.field.draw(ctx);
      if (this.mode === "controller") this.drawBird(ctx);
    }

    if (this.mode === "controller") {
      // The pad, drawn into the world: it is a place on the floor, and
      // the fly's own eyes should see it as one.
      const r = padPixels(FLAP_PAD, w, h);
      ctx.fillStyle = this.flapFlash > 0 ? "rgba(120, 200, 255, 0.30)" : "rgba(90, 130, 190, 0.13)";
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.strokeStyle = "rgba(150, 190, 240, 0.35)";
      ctx.lineWidth = 2;
      ctx.strokeRect(r.x + 1, r.y + 1, r.w - 2, r.h - 2);
    }
  }

  private drawBird(ctx: CanvasRenderingContext2D): void {
    const tilt = Math.max(-0.5, Math.min(0.9, this.birdV / 700));
    ctx.save();
    ctx.translate(BIRD_X, this.birdY);
    ctx.rotate(tilt);
    ctx.fillStyle = this.over ? "#8a6a3a" : "#e8c15a";
    ctx.beginPath();
    ctx.ellipse(0, 0, BIRD_R + 3, BIRD_R, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f2e0a8";
    ctx.beginPath();
    ctx.ellipse(-3, 2, 7, 5, this.flapFlash > 0 ? -0.7 : 0.25, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#3a2f18";
    ctx.beginPath();
    ctx.arc(6, -4, 2.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#d98b32";
    ctx.beginPath();
    ctx.moveTo(12, 0);
    ctx.lineTo(21, 3);
    ctx.lineTo(12, 6);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  drawOverlay(ctx: CanvasRenderingContext2D, w: number, _h: number): void {
    // Never sampled by the retina: the fly should not be reading its own
    // scoreboard.
    ctx.font = "600 34px ui-monospace, monospace";
    ctx.fillStyle = "rgba(232, 236, 241, 0.9)";
    ctx.textAlign = "center";
    ctx.fillText(String(this.score), w / 2, 52);
    if (this.over) {
      ctx.font = "600 15px ui-monospace, monospace";
      ctx.fillStyle = "rgba(255, 140, 120, 0.9)";
      ctx.fillText(
        this.mode === "controller" ? "the bird hit a pipe" : "the fly hit a pipe",
        w / 2,
        78,
      );
    }
  }
}
