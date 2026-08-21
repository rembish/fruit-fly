/**
 * The clock everything downstream runs on.
 *
 * There is one rule and the whole design rests on it: **nothing outside
 * the worker's scheduler may compare simulated time to wall time.** The
 * brain free-runs at whatever pace the machine allows, capped at 1x, and
 * reports how much simulated time it has produced. The body, the world
 * and the retina cadence all advance by that number.
 *
 * What this buys is that a slow machine is *slow*, not *broken*. The
 * motor map was calibrated against descending rates measured in
 * simulated seconds; a phone that manages a third of realtime shows the
 * whole fly in a third-speed slow motion, with every threshold, every
 * accumulator and every time constant still meaning what it meant when
 * they were tuned. The alternative — advancing the world by rAF's wall
 * clock while the brain lags — silently rescales every one of them, and
 * the failure looks like a fly that will not land rather than like a
 * clock bug.
 *
 * The cost is that "seconds" on screen are not the viewer's seconds.
 * That is the honest trade and the HUD says so.
 */
export class SimClock {
  /** Simulated ms most recently reported by the worker. */
  private simMs = 0;
  /** Simulated ms already handed out to the world. */
  private consumedMs = 0;
  private started = false;

  /** The worker has produced simulated time up to `simTimeMs`. */
  advanceTo(simTimeMs: number): void {
    if (!this.started) {
      // Do not hand the first frame the entire warm-up as one dt: the
      // brain has been running since it loaded, and a 3-second dt would
      // teleport the fly across the canvas on frame one.
      this.consumedMs = simTimeMs;
      this.started = true;
    }
    this.simMs = simTimeMs;
  }

  /**
   * Simulated seconds owed to the world since the last call.
   *
   * Clamped, because a tab that was in the background can come back with
   * a large debt and a single enormous dt integrates the body through
   * walls. Dropping the excess makes the fly's clock lose time, which is
   * the right failure: the alternative is a teleport.
   */
  take(maxSeconds = 0.1): number {
    const owed = (this.simMs - this.consumedMs) / 1000;
    if (owed <= 0) return 0;
    const dt = Math.min(owed, maxSeconds);
    this.consumedMs += dt * 1000;
    return dt;
  }

  /** Simulated seconds since the clock started. */
  get seconds(): number {
    return this.simMs / 1000;
  }

  get running(): boolean {
    return this.started;
  }
}
