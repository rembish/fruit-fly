import { describe, expect, it } from "vitest";
import { FLAP_PAD, PressDetector, onPad, padEligible } from "./pads.js";
import { ESCAPE, FLYING, LANDED, type MotorPhase } from "./motor.js";

const W = 960;
const H = 540;

function fly(x: number, y: number, state: MotorPhase = LANDED) {
  return { x, y, state };
}

describe("the FLAP pad", () => {
  it("is the bottom fifth, full width — the geometry M0.2 chose", () => {
    // The 10% bar M0.2 rejected got zero presses in two minutes because
    // edge avoidance turns the fly back before the floor; this pad
    // reaches up far enough to be where the fly actually flies.
    expect(FLAP_PAD.rect).toEqual([0.0, 0.8, 1.0, 1.0]);
    expect(onPad(FLAP_PAD, fly(480, 500), W, H)).toBe(true);
    expect(onPad(FLAP_PAD, fly(10, 440), W, H)).toBe(true); // full width
    expect(onPad(FLAP_PAD, fly(480, 400), W, H)).toBe(false); // above it
  });
});

describe("press eligibility", () => {
  it("needs the fly landed, not merely over the pad", () => {
    expect(padEligible(FLAP_PAD, fly(480, 500, LANDED), W, H)).toBe(true);
    expect(padEligible(FLAP_PAD, fly(480, 500, FLYING), W, H)).toBe(false);
    expect(padEligible(FLAP_PAD, fly(480, 500, ESCAPE), W, H)).toBe(false);
  });
});

describe("PressDetector", () => {
  it("counts a dwelling fly once", () => {
    // A held button would fire every frame. Four seconds of sitting is
    // one press, and this is the property M0.2's whole press rate rests
    // on.
    const d = new PressDetector();
    const st = fly(480, 500);
    expect(d.poll([FLAP_PAD], st, W, H)).toHaveLength(1);
    for (let i = 0; i < 240; i++) {
      expect(d.poll([FLAP_PAD], st, W, H)).toHaveLength(0);
    }
  });

  it("counts leaving and returning as two", () => {
    const d = new PressDetector();
    expect(d.poll([FLAP_PAD], fly(480, 500), W, H)).toHaveLength(1);
    d.poll([FLAP_PAD], fly(480, 200), W, H); // takes off
    expect(d.poll([FLAP_PAD], fly(480, 500), W, H)).toHaveLength(1);
  });

  it("ignores a fly crossing the pad without landing", () => {
    // The 1400 px/s escape dart. It is a startle, not a decision, and it
    // must not chord the game.
    const d = new PressDetector();
    for (let i = 0; i < 10; i++) {
      expect(
        d.poll([FLAP_PAD], fly(100 + i * 80, 500, ESCAPE), W, H),
      ).toHaveLength(0);
    }
  });

  it("ignores a fly cruising over it, however slowly", () => {
    // M0.2 measured identical press rates at landed-only, <=60 px/s and
    // <=120 px/s — every press was a landing, so the speed clause bought
    // nothing and does not exist here.
    const d = new PressDetector();
    for (let i = 0; i < 10; i++) {
      expect(d.poll([FLAP_PAD], fly(480, 500, FLYING), W, H)).toHaveLength(0);
    }
    // ... and the moment it puts its feet down, that is an arrival
    expect(d.poll([FLAP_PAD], fly(480, 500, LANDED), W, H)).toHaveLength(1);
  });

  it("tracks pads independently", () => {
    const other = { id: "other", label: "X", rect: [0, 0, 1, 0.2] } as const;
    const d = new PressDetector();
    const pads = [FLAP_PAD, other];
    expect(d.poll(pads, fly(480, 500), W, H).map((p) => p.id)).toEqual(["flap"]);
    expect(d.poll(pads, fly(480, 50), W, H).map((p) => p.id)).toEqual(["other"]);
  });

  it("forgets its history on reset, so a restart can arrive again", () => {
    const d = new PressDetector();
    const st = fly(480, 500);
    expect(d.poll([FLAP_PAD], st, W, H)).toHaveLength(1);
    expect(d.poll([FLAP_PAD], st, W, H)).toHaveLength(0);
    d.reset();
    expect(d.poll([FLAP_PAD], st, W, H)).toHaveLength(1);
  });
});
