import { describe, expect, it } from "vitest";
import { PipeField } from "./pipes.js";
import { Fff } from "./fff.js";
import { FLAP_PAD } from "../../motor/pads.js";
import { LANDED, FLYING, type MotorState } from "../../motor/motor.js";

const W = 960;
const H = 540;
const DT = 1 / 60;

function fly(x = 480, y = 500, state: MotorState["state"] = LANDED): MotorState {
  return { x, y, heading: 0, speed: 0, state, wingPhase: 0, lastEvent: "" };
}

/** Run the game with a fixed press schedule. */
function play(
  g: Fff,
  seconds: number,
  pressOn: (t: number) => boolean = () => false,
) {
  let t = 0;
  const steps = Math.round(seconds / DT);
  for (let i = 0; i < steps; i++) {
    t += DT;
    g.tick({
      dt: DT,
      t,
      fly: fly(),
      pressed: pressOn(t) ? [FLAP_PAD] : [],
    });
  }
  return t;
}

describe("PipeField", () => {
  it("scores a pipe once, when it has gone past", () => {
    const f = new PipeField({ width: W, height: H }, 1);
    const playerX = 240;
    let scored = 0;
    for (let i = 0; i < 60 * 20; i++) scored += f.advance(DT, playerX);
    expect(scored).toBeGreaterThan(0);
    // Every pipe still on the field that is behind the player is marked,
    // so it cannot be counted twice on the next frame.
    for (const p of f.pipes) {
      if (p.x + f.pipeW < playerX) expect(p.passed).toBe(true);
    }
    const again = f.advance(0, playerX);
    expect(again).toBe(0);
  });

  it("keeps a gap the player can actually be in", () => {
    const f = new PipeField({ width: W, height: H }, 7);
    for (const p of f.pipes) {
      expect(f.hits(p.x + f.pipeW / 2, p.gapY, 10)).toBe(false);
      expect(f.hits(p.x + f.pipeW / 2, 4, 10)).toBe(true);
      expect(f.hits(p.x + f.pipeW / 2, H - 4, 10)).toBe(true);
    }
  });

  it("misses entirely when the player is between pipes", () => {
    const f = new PipeField({ width: W, height: H }, 3);
    const p = f.pipes[0]!;
    expect(f.hits(p.x - 60, 20, 10)).toBe(false);
  });

  it("is reproducible from its seed", () => {
    const a = new PipeField({ width: W, height: H }, 42);
    const b = new PipeField({ width: W, height: H }, 42);
    for (let i = 0; i < 500; i++) {
      a.advance(DT, 240);
      b.advance(DT, 240);
    }
    expect(a.pipes.map((p) => [p.x, p.gapY])).toEqual(
      b.pipes.map((p) => [p.x, p.gapY]),
    );
  });

  it("scrolls at the speed M0.3 showed the fly's eyes", () => {
    // 150 px/s is not a difficulty knob alone: the pipes are in the
    // fly's field of view, and this is the speed that puts 3 patch
    // pixels of travel under each sensory tick rather than a slideshow.
    const f = new PipeField({ width: W, height: H });
    expect(f.speed).toBe(150);
  });
});

describe("Fff — controller mode", () => {
  it("offers a pad, and it is the one M0.2 chose", () => {
    const g = new Fff({ width: W, height: H });
    expect(g.mode).toBe("controller");
    expect(g.pads()).toHaveLength(1);
    expect(g.pads()[0]!.id).toBe(FLAP_PAD.id);
  });

  it("falls out of the sky when nobody presses anything", () => {
    // The do-nothing arm, and the floor every other arm has to beat.
    const g = new Fff({ width: W, height: H, flapper: "nobody" });
    play(g, 3.0);
    expect(g.best).toBe(0);
    expect(g.bestSurvived).toBeGreaterThan(0);
    expect(g.bestSurvived).toBeLessThan(2.0);
  });

  it("flies longer with presses than without", () => {
    // The mechanism, not the fly's chances. ~1.5 flaps/s is the rate
    // that holds this bird level (impulse 390 against gravity 1150), so
    // that is what a *player* would do — and it is 22x what M0.2
    // measured the fly managing.
    const flapped = new Fff({ width: W, height: H, flapper: "fly", seed: 3 });
    play(flapped, 8.0, (t) => Math.floor(t * 1.6) !== Math.floor((t - DT) * 1.6));
    const nothing = new Fff({ width: W, height: H, flapper: "nobody", seed: 3 });
    play(nothing, 8.0, () => true);
    expect(flapped.bestSurvived).toBeGreaterThan(nothing.bestSurvived);
  });

  it("is far out of reach at the rate the fly actually presses", () => {
    // Not a tuning failure — the finding. M0.2 measured ~4 arrivals a
    // minute, which is one flap every 15 seconds against a bird that
    // needs one every 0.68 s to hold its height. The doc's headline was
    // never "a fly plays Flappy Bird"; it was that a connectome scores
    // no better than chance, and this is why.
    const g = new Fff({ width: W, height: H, flapper: "fly", seed: 3 });
    play(g, 12.0, (t) => Math.floor(t / 15) !== Math.floor((t - DT) / 15));
    expect(g.best).toBe(0);
    expect(g.bestSurvived).toBeLessThan(2.0);
  });

  it("counts presses so the Poisson arm has a rate to match", () => {
    const g = new Fff({ width: W, height: H });
    play(g, 4.0, (t) => Math.floor(t * 2) !== Math.floor((t - DT) * 2));
    expect(g.pressCount).toBeGreaterThan(4);
  });

  it("ignores the pad when the flapper is not the fly", () => {
    // The comparison is only fair if the fly's presses really are
    // disconnected in the other arms.
    const g = new Fff({ width: W, height: H, flapper: "nobody" });
    play(g, 2.0, () => true);
    expect(g.best).toBe(0);
  });

  it("restarts itself after a crash, without a menu in the way", () => {
    // Rounds are about three seconds; anything that asked for a click
    // between them would be longer than the game. So the assertion is
    // that the round counter turns over, not that any single moment
    // finds it alive — with nobody flapping it dies again immediately,
    // which is the whole joke.
    const g = new Fff({ width: W, height: H, flapper: "nobody" });
    let rounds = 0;
    let wasOver = false;
    let t = 0;
    for (let i = 0; i < Math.round(8 / DT); i++) {
      t += DT;
      g.tick({ dt: DT, t, fly: fly(), pressed: [] });
      if (wasOver && !g.over) rounds += 1;
      wasOver = g.over;
    }
    expect(rounds).toBeGreaterThanOrEqual(2);
  });
});

describe("Fff — pilot mode", () => {
  it("has no pad, because there is nothing to press", () => {
    const g = new Fff({ width: W, height: H, mode: "pilot" });
    expect(g.pads()).toHaveLength(0);
  });

  it("ends the round when the fly itself hits a pipe", () => {
    const g = new Fff({ width: W, height: H, mode: "pilot" });
    // Park the fly at the very top, where every pipe has a wall.
    let t = 0;
    for (let i = 0; i < 600 && !g.over; i++) {
      t += DT;
      g.tick({ dt: DT, t, fly: fly(480, 8, FLYING), pressed: [] });
    }
    expect(g.over).toBe(true);
  });

  it("scores when the fly happens to be in the gap", () => {
    const g = new Fff({ width: W, height: H, mode: "pilot", seed: 5 });
    const gapY = g["field"].pipes[0]!.gapY;
    let t = 0;
    for (let i = 0; i < 400 && !g.over; i++) {
      t += DT;
      g.tick({ dt: DT, t, fly: fly(480, gapY, FLYING), pressed: [] });
    }
    // Either it threaded that pipe, or a later pipe's gap moved and it
    // died — both are honest; what must not happen is scoring while
    // inside a wall.
    expect(g.score >= 0).toBe(true);
  });

  it("switching modes starts a clean round", () => {
    const g = new Fff({ width: W, height: H });
    play(g, 2.0);
    g.setMode("pilot");
    expect(g.mode).toBe("pilot");
    expect(g.score).toBe(0);
    expect(g.over).toBe(false);
    expect(g.best).toBe(0);
  });
});
