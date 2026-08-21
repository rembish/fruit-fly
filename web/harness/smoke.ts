/**
 * Does the fly actually fly, in a real browser?
 *
 * Everything else in this repo's web half is checked without a DOM:
 * types, unit tests, the parity gate. None of that can tell you whether
 * the worker ever received a patch, whether `getImageData` on the
 * offscreen canvas returns what the retina expects, or whether the body
 * moves. Those are exactly the failures that survive a green test suite
 * and greet the first person to open the page.
 *
 * So this drives the page headlessly and asserts on what the fly does:
 * the brain loads, simulated time advances, the descending pool settles
 * where Python says it should, and a cursor put on the fly frightens it.
 *
 *   npm run smoke      (needs `npm run dev` running, and brain.bin)
 */

import { chromium, type ConsoleMessage } from "playwright";

const URL_ = process.env["SMOKE_URL"] ?? "http://localhost:5173/";

interface Hud {
  simSpeed: number;
  spikesPerSecond: number;
  threat: number;
  state: string;
  lastEvent: string;
  simSeconds: number;
  rates: Record<string, number>;
  x: number;
  y: number;
}

/** Bridge the controller out to the test, since the page owns it. */
const EXPOSE = `
  window.__hud = () => {
    const h = window.__controller.hud();
    const st = window.__controller.motor.st;
    return { ...h, x: st.x, y: st.y };
  };
`;

async function main(): Promise<number> {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const problems: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  console.log(`opening ${URL_}`);
  await page.goto(URL_, { waitUntil: "domcontentloaded" });
  await page.addScriptTag({ content: EXPOSE });

  // The brain is 17 MB and then has to be wired; the loading panel going
  // away is the page's own signal that it is ready.
  await page.waitForFunction(
    () => (document.getElementById("loading") as HTMLElement).style.display === "none",
    undefined,
    { timeout: 120_000 },
  );
  console.log("brain loaded");

  const read = () => page.evaluate(() => (window as never as { __hud(): Hud }).__hud());

  const t0 = await read();
  // Sample across the window rather than at its ends: with the eyes open
  // in a moving scene the descending pool swings, and one reading says
  // nothing about whether it is alive or stuck.
  let descLo = Infinity;
  let descHi = -Infinity;
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(200);
    const s = await read();
    const d = s.rates["descending"] ?? 0;
    descLo = Math.min(descLo, d);
    descHi = Math.max(descHi, d);
  }
  const t1 = await read();

  const check = (ok: boolean, label: string, detail: string) => {
    console.log(`  ${ok ? "ok  " : "FAIL"}  ${label.padEnd(34)} ${detail}`);
    if (!ok) problems.push(label);
  };

  console.log("");
  const advanced = t1.simSeconds - t0.simSeconds;
  check(advanced > 1.0, "simulated time advances", `${advanced.toFixed(2)}s in 6s wall`);
  check(
    t1.simSpeed > 0.15 && t1.simSpeed <= 1.2,
    "sim speed is sane and capped",
    `${t1.simSpeed.toFixed(2)}x`,
  );
  check(
    t1.spikesPerSecond > 1000,
    "the network is alive",
    `${(t1.spikesPerSecond / 1000).toFixed(1)}k spikes/s`,
  );

  // Not 5.75. That is the *blind* figure the Phase 1 gate pins, and a
  // seeing fly in a moving scene runs well under it: every edge crossing
  // the retina is a darkening transient, the lamina answers, and L1's
  // output is 99.6% inhibitory. Measured at ~3 Hz here against 5.65 on a
  // flat field, which `harness/sense-parity.ts` is the gate for. This
  // check is a liveness bound, not a parity one — the exact number
  // belongs to the scene, and the scene is Phase 3's to choose.
  check(
    descLo > 0.2 && descHi < 30 && descHi > descLo,
    "descending pool alive and moving",
    `${descLo.toFixed(1)}-${descHi.toFixed(1)} Hz ` +
      `(blind 5.75, flat-field 5.65 — vision swings it)`,
  );

  const moved = Math.hypot(t1.x - t0.x, t1.y - t0.y);
  check(moved > 5 || t1.state === "landed", "the body is being driven", `moved ${moved.toFixed(0)} px, state ${t1.state}`);

  // Sabotage: put the pointer on the fly and see if it minds. The cursor
  // is not in the retina's pixels — it enters through the perspective
  // path — so this exercises that whole route.
  const box = (await page.locator("#view").boundingBox())!;
  const toPage = (x: number, y: number) => ({
    x: box.x + (x / 960) * box.width,
    y: box.y + (y / 540) * box.height,
  });
  let peakThreat = 0;
  const events = new Set<string>();
  // The fly's own narration rather than its instantaneous state: an
  // escape lasts 0.22 *simulated* seconds and hands straight back to
  // flight, so polling for the state is polling for a window that a
  // slow machine makes narrower still. `lastEvent` persists.
  for (let i = 0; i < 90; i++) {
    const cur = await read();
    const p = toPage(cur.x, cur.y);
    await page.mouse.move(p.x, p.y);
    await page.waitForTimeout(100);
    const after = await read();
    peakThreat = Math.max(peakThreat, after.threat);
    if (after.state === "escape" || after.state === "takeoff") {
      events.add(after.state);
    }
    if (after.lastEvent) events.add(after.lastEvent);
  }
  const frightened = [...events].filter((e) =>
    /escape|scrambling|looming|jink|takeoff/i.test(e),
  );
  check(peakThreat > 0.5, "the fly registers the cursor", `peak threat ${peakThreat.toFixed(2)}`);
  check(
    frightened.length > 0,
    "and is frightened by it",
    frightened.length ? `"${frightened[0]}"` : `never reacted (saw: ${[...events].join(" | ") || "nothing"})`,
  );

  await browser.close();

  console.log("");
  if (problems.length) {
    console.log(`SMOKE FAILED: ${problems.length} problem(s)`);
    for (const p of problems) console.log(`  - ${p}`);
    return 1;
  }
  console.log("SMOKE OK: the fly loads, runs, sees the cursor and bolts");
  return 0;
}

main().then(
  (code) => process.exit(code),
  (e: unknown) => {
    console.error(e);
    process.exit(1);
  },
);
