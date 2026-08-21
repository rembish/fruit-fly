/**
 * Phase 2 bench: wire the brain, the body and a canvas together and let
 * the thing fly. No game yet — that is Phase 3. What this page proves is
 * that the ported brain drives a body through real eyes in a browser.
 *
 * The "world" is deliberately plain but not empty: the retina needs
 * something with contrast to look at, and a uniform field would make the
 * eyes a very expensive way of computing nothing.
 */

import { Controller, CANVAS_W, CANVAS_H } from "../runtime/controller.js";
import type { FromWorker, StartMessage } from "../runtime/protocol.js";

const view = document.getElementById("view") as HTMLCanvasElement;
const loading = document.getElementById("loading") as HTMLDivElement;
const bar = document.querySelector("#bar div") as HTMLDivElement;
const note = document.getElementById("note") as HTMLDivElement;
const hud = document.getElementById("hud") as HTMLDivElement;
const eventLine = document.getElementById("event") as HTMLDivElement;
const pokeBar = document.getElementById("poke") as HTMLDivElement;

/** Populations worth a button: what the desktop's poke panel offers. */
const POKE_BUTTONS = [
  ["GF", "escape"],
  ["DNa02_L", "turn left"],
  ["DNa02_R", "turn right"],
  ["DNp09", "forward"],
  ["MDN", "backward"],
  ["LC4_L", "loom, left eye"],
  ["JO", "a swat, felt"],
] as const;

/**
 * A floor with a horizon and some furniture.
 *
 * Contrast is the point. Static structure is nearly invisible to this
 * visual system once adaptation has caught up — M0.1 measured that a
 * held brightness does essentially nothing — so what the fly reacts to
 * here is the cursor, which moves. The scenery exists so the retina has
 * a baseline to adapt *to*.
 */
function drawWorld(ctx: CanvasRenderingContext2D, t: number): void {
  const sky = ctx.createLinearGradient(0, 0, 0, CANVAS_H);
  sky.addColorStop(0, "#1b2230");
  sky.addColorStop(0.68, "#232c3b");
  sky.addColorStop(0.7, "#2f2a24");
  sky.addColorStop(1, "#191510");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  // A slow drift, so the eyes have something with a time constant to
  // chew on rather than a frozen photograph.
  const drift = Math.sin(t * 0.05) * 18;
  ctx.fillStyle = "rgba(255, 246, 224, 0.05)";
  for (let i = 0; i < 7; i++) {
    const x = ((i * 151 + drift) % (CANVAS_W + 160)) - 80;
    ctx.beginPath();
    ctx.ellipse(x, 90 + (i % 3) * 34, 70, 16, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.strokeStyle = "rgba(120, 132, 150, 0.18)";
  ctx.lineWidth = 1;
  for (let y = CANVAS_H * 0.72; y < CANVAS_H; y += 26) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(CANVAS_W, y);
    ctx.stroke();
  }
}

function main(): void {
  const worker = new Worker(
    new URL("../runtime/worker.ts", import.meta.url),
    { type: "module" },
  );
  const controller = new Controller(view, worker, drawWorld);
  // Handle for `harness/smoke.ts`, which drives this page in a real
  // browser and asks the fly what it is doing. Nothing in the app reads
  // it back.
  (window as unknown as { __controller: Controller }).__controller = controller;

  controller.onEvent = (text) => {
    eventLine.textContent = text;
  };

  // The worker owns the brain, so the page listens in rather than asking.
  // The controller is listening on the same worker for ticks; both use
  // addEventListener so neither can unhook the other.
  worker.addEventListener("message", (ev: MessageEvent<FromWorker>) => {
    const msg = ev.data;
    if (msg.kind === "progress") {
      note.textContent = msg.note;
      bar.style.width = `${Math.round((msg.loaded ?? 0) * 100)}%`;
    } else if (msg.kind === "ready") {
      loading.style.display = "none";
      note.textContent = "";
      buildPokeBar(controller, new Set(msg.pops));
      console.info(
        `${msg.neurons.toLocaleString()} neurons, ` +
          `${msg.connections.toLocaleString()} connections\n${msg.attribution}`,
      );
    } else if (msg.kind === "error") {
      loading.style.display = "grid";
      note.textContent = `could not load the brain: ${msg.message}`;
      bar.style.width = "0";
    }
  });

  const start: StartMessage = {
    kind: "start",
    brainUrl: "/brain/brain.bin",
    seed: 7,
    noiseRate: 100,
    noiseWeight: 3,
    inhGain: 1.5,
    dt: 2.0,
    // The disclosed safety net, at the desktop's value. M0.3 measured
    // what the eyes alone do with an approaching object: they move the
    // loom detectors by half and never reach the giant fiber. Set this
    // to 0 and the fly stops escaping the cursor.
    loomInjection: 0.4,
  };
  worker.postMessage(start);

  const fmt = (v: number, d = 1) => v.toFixed(d).padStart(6);
  const loop = () => {
    controller.frame();
    const h = controller.hud();
    hud.textContent =
      `sim ${fmt(h.simSpeed, 2)}x   ${fmt(h.spikesPerSecond / 1000)}k spikes/s   ` +
      `t ${fmt(h.simSeconds)}s (simulated)\n` +
      `threat ${fmt(h.threat, 2)}   state ${h.state.padEnd(9)}\n` +
      ["GF", "DNa02_L", "DNa02_R", "descending"]
        .map((k) => `${k} ${fmt(h.rates[k] ?? 0)}Hz`)
        .join("   ") +
      "\n" +
      ["LC4_L", "LC4_R"]
        .map((k) => `${k} ${fmt(h.rates[k] ?? 0)}Hz`)
        .join("   ") +
      "   (loom detectors)";
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function buildPokeBar(controller: Controller, available: Set<string>): void {
  pokeBar.replaceChildren();
  for (const [pop, label] of POKE_BUTTONS) {
    if (!available.has(pop)) continue;
    const b = document.createElement("button");
    b.textContent = `${pop} — ${label}`;
    b.addEventListener("click", () => controller.poke(pop, 120, 0.4));
    pokeBar.append(b);
  }
}

main();
