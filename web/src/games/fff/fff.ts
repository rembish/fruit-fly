/**
 * Fruit Flappy Fly, in two modes, because they are two different claims.
 *
 * **controller** — the design doc's game, and the joke it was built
 * around. A bird falls under gravity and flaps when, and only when, the
 * fly presses the plate in its own chamber. The fly is
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
 * has to be read with it in mind. The scene toggle exists for that.
 */

import type { Game, GameContext } from "../api.js";
import { padPixels, type Pad, type PadSensor } from "../../motor/pads.js";
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
  /** How the plate decides it is pressed. See `PadSensor`. */
  sensor?: PadSensor;
  seed?: number;
}

/** Bird physics, in pixels and simulated seconds. */
const GRAVITY = 1150;
const FLAP_IMPULSE = -390;
const MAX_FALL = 620;
/**
 * How much of its speed the bird keeps off a wall.
 *
 * Well under half, so a bird dropped from height settles rather than
 * pogoing forever — a bouncing castle would read as a physics bug.
 */
const BOUNCE = 0.42;
/**
 * The bird's column.
 *
 * Right of the fly's chamber, and far enough right that a pipe entering
 * from the edge gives the bird several seconds of runway. With the
 * chamber on the right and the bird at 180 it had 5.2 s before the first
 * pipe — and every arm, including the one nobody was flapping, died at
 * exactly 5.1 s, because the round was decided by the pipe's arrival
 * rather than by anything the flapper did.
 */
const BIRD_X = 560;
const BIRD_R = 13;

/**
 * The fly's chamber, in canvas fractions: a box on the left.
 *
 * On the left because the pipes scroll in from the right and out to the
 * left: a chamber on the entry side stands exactly where the game needs
 * to be visible, and pushes the bird so far left that it meets its first
 * pipe before it has done anything.
 *
 * This is what an input device is, physically — a fly in a jar with a
 * pressure plate in it, not a fly loose over the playfield. It
 * also changes the mechanism's arithmetic completely, and in the fly's
 * favour: M0.2's ~4 presses a minute is what a fly does when it has a
 * whole 960x540 to wander, and a fly kept a few body-lengths from the
 * plate meets it far more often. That number has to be re-measured
 * here rather than carried over, which is what the plan's "re-measure
 * padstats" clause was always going to mean.
 *
 * The chamber sits inside the same canvas the retina samples, so the fly
 * can still see the game scrolling past outside its walls. That is the
 * doc's arrangement, kept: the pipes loom in a real optic lobe.
 */
export const FLY_BOX: readonly [number, number, number, number] = [
  0.015, 0.08, 0.33, 0.94,
];

/**
 * The plate: the lower part of the chamber.
 *
 * Sized by a mistake worth recording. It started as a thin strip along
 * the chamber floor, on the assumption that a fly settles downward — and
 * measured **zero presses in 26 simulated seconds**, with the fly parked
 * two-thirds of the way *up* the box. The desktop fly is a top-down
 * animal: `LANDED` means "feet down on the surface", and the surface is
 * the whole plane, so it sits wherever it stopped rather than falling to
 * a floor. There is no gravity in the motor map and there never was.
 *
 * So the plate is a broad region of the chamber rather than a ledge at
 * the bottom of it, and the fly meets it by wandering onto it — which is
 * exactly how M0.2's pads worked, in the arena M0.2 measured.
 *
 * It splits the chamber in half: the lower half flaps, the upper half
 * does not. Edge avoidance pulls the fly toward the middle of its box,
 * so the fly lives right on that line and the bird's altitude tracks
 * which side of it the fly happens to be drifting on. That is the whole
 * control loop, and it is why the split is the middle rather than
 * anywhere else — put the line elsewhere and the fly sits on one side of
 * it permanently.
 */
/**
 * How often a held plate fires again, in simulated seconds.
 *
 * The plate is half the chamber and the fly spends roughly half its time
 * there, so the flap rate the bird actually sees is about half of
 * 1/0.3 — call it 1.7 a second, against the 1.5 it needs to hold its
 * height. That thin margin is the whole game: linger low and the bird
 * climbs, drift high and it sinks.
 *
 * At 0.45 s the margin ran the other way (1.1 against 1.5) and the bird
 * sank every time, dying at the first pipe in every arm including the
 * one nobody was flapping. This is the one number on the page chosen for
 * playability rather than measured, which is said plainly rather than
 * buried — but it is applied identically to all three arms, so what the
 * comparison between them measures is untouched.
 */
export const PLATE_REPEAT_S = 0.3;

export const BOX_PAD: Pad = {
  id: "flap",
  label: "FLAP",
  rect: [FLY_BOX[0], 0.51, FLY_BOX[2], FLY_BOX[3]],
};

export class Fff implements Game {
  readonly id = "fff";
  readonly name = "Fruit Flappy Fly";

  mode: FffMode;
  flapper: Flapper;
  scene: boolean;
  sensor: PadSensor;

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
  /** Why the round ended, for the overlay. */
  cause = "";
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
    this.sensor = opts.sensor ?? "passing";
    this.rng = (opts.seed ?? 99) >>> 0;
    this.field = new PipeField({ width: this.w, height: this.h }, opts.seed);
    this.reset();
  }

  /** Lowest point of the bird, for tests that care about the floor. */
  get birdBottom(): number {
    return this.birdY + BIRD_R;
  }

  /** The bird's height. Read by the benchmark's positive control only —
   *  no arm under test may look at this. */
  get birdHeight(): number {
    return this.birdY;
  }

  /** Centre of the next gap the bird has not yet cleared. */
  get nextGapY(): number {
    for (const p of this.field.pipes) {
      if (!p.passed) return p.gapY;
    }
    return this.h / 2;
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
    return this.mode === "controller" ? [BOX_PAD] : [];
  }

  padSensor(): PadSensor {
    return this.sensor;
  }

  padRepeat(): number {
    return PLATE_REPEAT_S;
  }

  flyBounds(): readonly [number, number, number, number] | null {
    // Pilot mode gives the fly the whole field, because there it *is*
    // the player and a chamber would be a cage rather than a joystick.
    return this.mode === "controller" ? FLY_BOX : null;
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
      let flapped = ctx.pressed.some((p) => p.id === BOX_PAD.id);
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

      // Floor and ceiling bounce rather than kill. Not a kindness to the
      // fly: at a press rate this low almost every round was ending on
      // the ground before a pipe was ever reached, so the game the page
      // claims to be measuring was never actually being played. The rule
      // is identical for all three arms, so the comparison between them
      // is untouched — and a bird nobody flaps still dies on the first
      // pipe, because the gaps are above the floor it is skidding along.
      if (this.birdY + BIRD_R > this.h) {
        this.birdY = this.h - BIRD_R;
        this.birdV = -Math.abs(this.birdV) * BOUNCE;
      } else if (this.birdY - BIRD_R < 0) {
        this.birdY = BIRD_R;
        this.birdV = Math.abs(this.birdV) * BOUNCE;
      }
      this.score += this.field.advance(dt, BIRD_X);
      if (this.field.hits(BIRD_X, this.birdY, BIRD_R)) {
        this.die("the bird hit a pipe");
      }
    } else {
      // Pilot: the fly's own body is the player. Nothing here moves it —
      // the motor map does, out of descending drive, and the pipes are
      // simply in the way.
      this.score += this.field.advance(dt, ctx.fly.x);
      if (this.field.hits(ctx.fly.x, ctx.fly.y, 12)) this.die("the fly hit a pipe");
    }
  }

  private die(cause: string): void {
    this.cause = cause;
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

    // `scene` decides who the pipes are drawn *for*, never whether they
    // are drawn. With it on they go into the world canvas, which is what
    // the retina samples, so they loom in a real optic lobe. With it off
    // they move to the overlay: the fly cannot see them and the viewer
    // still can. Skipping them entirely blinded the audience too, which
    // made the control useless as a thing to watch.
    // Chamber first, pipes second. Painted the other way round the glass
    // laid 55% dark over the pipes crossing behind it — dimming the one
    // thing the fly is supposed to be able to see, and making the
    // "pipes in the fly's eyes" control measure as nothing when the
    // cause was this fill rather than the layout.
    if (this.mode === "controller") this.drawChamber(ctx, w, h);
    if (this.scene) this.drawGame(ctx);
    if (this.mode === "controller") this.drawChamberFrame(ctx, w, h);
  }

  /** The pipes and the bird — the part of the picture the fly may or may
   *  not be allowed to see. */
  private drawGame(ctx: CanvasRenderingContext2D): void {
    this.field.draw(ctx);
    if (this.mode === "controller") this.drawBird(ctx);
  }

  /**
   * The fly's box, and the button that is its floor.
   *
   * Drawn into the world canvas rather than the overlay, deliberately:
   * the fly's own eyes should see the walls it keeps meeting and the
   * plate it keeps landing on. Whether that matters is a real question —
   * the walls are the strongest vertical edges in its visual field.
   */
  private drawChamber(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const x0 = FLY_BOX[0] * w;
    const y0 = FLY_BOX[1] * h;
    const x1 = FLY_BOX[2] * w;
    const y1 = FLY_BOX[3] * h;

    // Glass: dark enough to read as an enclosure, light enough that the
    // pipes behind it stay visible to a viewer.
    ctx.fillStyle = "rgba(10, 14, 20, 0.55)";
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    ctx.strokeStyle = "rgba(150, 190, 240, 0.30)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);

    const r = padPixels(BOX_PAD, w, h);
    ctx.fillStyle =
      this.flapFlash > 0 ? "rgba(120, 200, 255, 0.38)" : "rgba(90, 130, 190, 0.16)";
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = "rgba(150, 190, 240, 0.45)";
    ctx.strokeRect(r.x + 1, r.y + 1, r.w - 2, r.h - 2);
    ctx.font = "600 12px ui-monospace, monospace";
    ctx.fillStyle = "rgba(190, 215, 245, 0.55)";
    ctx.textAlign = "center";
    ctx.fillText("FLAP", (r.x + r.w / 2), r.y + r.h / 2 + 4);
    ctx.textAlign = "left";
  }

  /** The glass, drawn again over the pipes so the box still reads as an
   *  enclosure rather than a rectangle the scenery ignores. Outline
   *  only: a fill here would undo the whole point of the reorder. */
  private drawChamberFrame(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
  ): void {
    const x0 = FLY_BOX[0] * w;
    const y0 = FLY_BOX[1] * h;
    const x1 = FLY_BOX[2] * w;
    const y1 = FLY_BOX[3] * h;
    ctx.strokeStyle = "rgba(150, 190, 240, 0.55)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
    const split = BOX_PAD.rect[1] * h;
    ctx.strokeStyle = "rgba(150, 190, 240, 0.35)";
    ctx.beginPath();
    ctx.moveTo(x0, split);
    ctx.lineTo(x1, split);
    ctx.stroke();
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
    // Never sampled by the retina, which is exactly why the pipes come
    // here when the fly is meant to be blind to them.
    if (!this.scene) this.drawGame(ctx);
    ctx.font = "600 34px ui-monospace, monospace";
    ctx.fillStyle = "rgba(232, 236, 241, 0.9)";
    ctx.textAlign = "center";
    ctx.fillText(String(this.score), w / 2, 52);
    if (this.over) {
      ctx.font = "600 15px ui-monospace, monospace";
      ctx.fillStyle = "rgba(255, 140, 120, 0.9)";
      ctx.fillText(this.cause, w / 2, 78);
    }
  }
}
