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
    // One enormous dt would integrate the body straight through the
    // canvas walls.
    const c = new SimClock();
    c.advanceTo(0);
    c.advanceTo(120_000);
    expect(c.take(0.1)).toBe(0.1);
  });

  it("does not fast-forward after a background tab either", () => {
    // The bug this exists for, and the one the test above missed by
    // checking a single call. A hidden tab pauses requestAnimationFrame
    // while the worker keeps producing simulated time; clamping only the
    // step left the debt owed, and it was then handed out at 0.1 s per
    // frame, sixty frames a second — six times realtime for as long as
    // the tab had been away. Clamping the step is not the same as
    // clamping the backlog.
    const c = new SimClock();
    c.advanceTo(0);
    c.advanceTo(120_000); // two minutes away
    let handedOut = 0;
    for (let i = 0; i < 100; i++) handedOut += c.take(0.1, 0.25);
    expect(handedOut).toBeLessThanOrEqual(0.25 + 1e-9);
  });

  it("still smooths over a dropped frame or two", () => {
    // The backlog cap must not be so tight that ordinary jitter costs
    // time: a couple of missed frames should be made up, not discarded.
    const c = new SimClock();
    c.advanceTo(0);
    c.advanceTo(50); // ~three frames' worth arrived at once
    let handedOut = 0;
    for (let i = 0; i < 10; i++) handedOut += c.take(0.1, 0.25);
    expect(handedOut).toBeCloseTo(0.05, 9);
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
