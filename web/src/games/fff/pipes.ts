/**
 * The pipe field: geometry, scrolling, collision, scoring.
 *
 * Shared by both modes of Fruit Flappy Fly, because the pipes do not
 * care who is dodging them — a bird the fly is flapping, or the fly
 * itself. Keeping this pure and separate is what makes the two modes
 * comparable rather than two games that happen to look alike.
 *
 * All motion is per **simulated** second.
 */

export interface Pipe {
  /** Left edge, pixels. */
  x: number;
  /** Centre of the gap, pixels from the top. */
  gapY: number;
  /** Already counted toward the score. */
  passed: boolean;
}

export interface PipeFieldOptions {
  width: number;
  height: number;
  /** Pixels per simulated second. */
  speed?: number;
  /** Horizontal spacing between pipes. */
  spacing?: number;
  /** Wall thickness. */
  pipeW?: number;
  /** Vertical opening. */
  gapH?: number;
  /** Where gaps may sit, as fractions of the height. */
  gapRange?: readonly [number, number];
  /** Extra distance before the first pipe, so a round has a run-up. */
  leadIn?: number;
}

/**
 * Scroll speed, and why this number.
 *
 * 150 px/s is what M0.3 measured the fly's optic lobe against — an eye
 * spans 240 screen px over 96 patch px, so this moves a pipe 3 patch
 * pixels per sensory tick, which is motion rather than a slideshow. The
 * pipes are in the fly's field of view by design, so their speed is a
 * stimulus parameter and not only a difficulty knob.
 */
const DEFAULT_SPEED = 150;

export class PipeField {
  readonly pipes: Pipe[] = [];
  private sinceSpawn = 0;
  private rngState: number;

  readonly width: number;
  readonly height: number;
  readonly speed: number;
  readonly spacing: number;
  readonly pipeW: number;
  readonly gapH: number;
  private readonly gapRange: readonly [number, number];
  private readonly leadIn: number;

  constructor(opts: PipeFieldOptions, seed = 12345) {
    this.width = opts.width;
    this.height = opts.height;
    this.speed = opts.speed ?? DEFAULT_SPEED;
    this.spacing = opts.spacing ?? 280;
    this.pipeW = opts.pipeW ?? 58;
    this.gapH = opts.gapH ?? 168;
    this.gapRange = opts.gapRange ?? [0.25, 0.72];
    // Without this the first pipe is already on screen when the round
    // begins, and at 150 px/s it reaches the bird before the flapper has
    // done anything — every arm, including the one nobody was flapping,
    // died at the identical second. The round has to be decided by the
    // flapping, not by the timetable.
    this.leadIn = opts.leadIn ?? 340;
    this.rngState = seed >>> 0;
    this.reset();
  }

  /** Small xorshift, local so a round is reproducible from its seed. */
  private rand(): number {
    let x = this.rngState;
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    this.rngState = x >>> 0;
    return this.rngState / 4294967296;
  }

  private newGapY(): number {
    const [lo, hi] = this.gapRange;
    return this.height * (lo + (hi - lo) * this.rand());
  }

  reset(): void {
    this.pipes.length = 0;
    this.sinceSpawn = 0;
    // Start with the field already populated, so a round begins with
    // something on screen rather than several empty seconds.
    for (let i = 0; i < 3; i++) {
      this.pipes.push({
        x: this.width + this.leadIn + i * this.spacing,
        gapY: this.newGapY(),
        passed: false,
      });
    }
  }

  /** Advance by `dt` simulated seconds; return how many pipes were cleared. */
  advance(dt: number, playerX: number): number {
    const travelled = this.speed * dt;
    this.sinceSpawn += travelled;
    let scored = 0;

    for (const p of this.pipes) {
      p.x -= travelled;
      if (!p.passed && p.x + this.pipeW < playerX) {
        p.passed = true;
        scored += 1;
      }
    }
    while (this.pipes.length && this.pipes[0]!.x + this.pipeW < -20) {
      this.pipes.shift();
    }
    if (this.sinceSpawn >= this.spacing) {
      this.sinceSpawn -= this.spacing;
      const last = this.pipes[this.pipes.length - 1];
      this.pipes.push({
        x: last ? last.x + this.spacing : this.width,
        gapY: this.newGapY(),
        passed: false,
      });
    }
    return scored;
  }

  /** Does a circle at (x, y) touch any wall? */
  hits(x: number, y: number, r: number): boolean {
    for (const p of this.pipes) {
      if (x + r < p.x || x - r > p.x + this.pipeW) continue;
      const top = p.gapY - this.gapH / 2;
      const bottom = p.gapY + this.gapH / 2;
      if (y - r < top || y + r > bottom) return true;
    }
    return false;
  }

  draw(ctx: CanvasRenderingContext2D): void {
    for (const p of this.pipes) {
      const top = p.gapY - this.gapH / 2;
      const bottom = p.gapY + this.gapH / 2;
      const g = ctx.createLinearGradient(p.x, 0, p.x + this.pipeW, 0);
      g.addColorStop(0, "#2f6b3f");
      g.addColorStop(0.45, "#48a05c");
      g.addColorStop(1, "#245233");
      ctx.fillStyle = g;
      ctx.fillRect(p.x, 0, this.pipeW, top);
      ctx.fillRect(p.x, bottom, this.pipeW, this.height - bottom);
      // Lips, which are also the strongest horizontal edges the fly's
      // retina gets from this scene.
      ctx.fillStyle = "#173d24";
      ctx.fillRect(p.x - 4, top - 16, this.pipeW + 8, 16);
      ctx.fillRect(p.x - 4, bottom, this.pipeW + 8, 16);
    }
  }
}
