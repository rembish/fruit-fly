import { describe, expect, it } from "vitest";
import { SimClock } from "./simclock.js";

describe("SimClock", () => {
  it("hands out exactly the simulated time the brain produced", () => {
    const c = new SimClock();
    c.advanceTo(1000); // the warm-up: consumed, not handed out
    expect(c.take()).toBe(0);
    c.advanceTo(1016);
    expect(c.take()).toBeCloseTo(0.016, 9);
    expect(c.take()).toBe(0); // nothing new since
  });

  it("loses no time across many small reads", () => {
    // The body integrates position from these; a clock that dropped a
    // millisecond per frame would slow the fly by 6% and nobody would
    // ever find it.
    const c = new SimClock();
    c.advanceTo(0);
    let total = 0;
    for (let i = 1; i <= 600; i++) {
      c.advanceTo(i * 16);
      total += c.take();
    }
    expect(total).toBeCloseTo(9.6, 9);
  });

  it("does not teleport the fly after a background tab", () => {
    // A tab that was hidden comes back owing minutes. One enormous dt
    // integrates the body straight through the canvas walls, so the
    // excess is dropped: the fly's clock loses time, which is the right
    // failure of the two.
    const c = new SimClock();
    c.advanceTo(0);
    c.advanceTo(120_000);
    expect(c.take(0.1)).toBe(0.1);
  });

  it("reports simulated seconds, not wall seconds", () => {
    const c = new SimClock();
    c.advanceTo(2500);
    expect(c.seconds).toBe(2.5);
  });

  it("is not running until the brain has reported something", () => {
    const c = new SimClock();
    expect(c.running).toBe(false);
    c.advanceTo(0);
    expect(c.running).toBe(true);
  });
});
