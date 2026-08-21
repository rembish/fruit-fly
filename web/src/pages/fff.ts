/**
 * Fruit Flappy Fly, both modes, switchable while it runs.
 *
 * The switch is the point of this page. The two modes make different
 * claims and the only way to judge which is the better cabinet is to
 * watch the same brain do both, with everything else held fixed — same
 * fly, same seed, same pipes, same clock.
 */

import { Controller, CANVAS_W, CANVAS_H } from "../runtime/controller.js";
import { Fff, type FffMode, type Flapper } from "../games/fff/fff.js";
import type { FromWorker, StartMessage } from "../runtime/protocol.js";

const view = document.getElementById("view") as HTMLCanvasElement;
const loading = document.getElementById("loading") as HTMLDivElement;
const bar = document.querySelector("#bar div") as HTMLDivElement;
const note = document.getElementById("note") as HTMLDivElement;
const hud = document.getElementById("hud") as HTMLDivElement;
const eventLine = document.getElementById("event") as HTMLDivElement;
const controls = document.getElementById("controls") as HTMLDivElement;
const explain = document.getElementById("explain") as HTMLParagraphElement;

const MODE_TEXT: Record<FffMode, string> = {
  controller:
    "The fly is the joystick, and has no idea a game is happening. Its chamber is split across the middle: " +
    "while the fly is drifting through the lower half the bird flaps, and while it is in the upper half the bird falls. " +
    "Nothing puts the fly on either side — it is a fly, and where it goes is whatever 139,255 neurons decide.",
  pilot:
    "The fly is the bird. No chamber, no proxy: the pipes come at it and its own body has to be in the gap. " +
    "Nothing is aiming it — a bright gap does not attract this connectome, which was measured before any of this was drawn — " +
    "so it is not a game the fly can win. It is a way of watching what a brain does when a wall arrives.",
};

function main(): void {
  const worker = new Worker(new URL("../runtime/worker.ts", import.meta.url), {
    type: "module",
  });
  const controller = new Controller(view, worker, () => {});
  const game = new Fff({ width: CANVAS_W, height: CANVAS_H });
  controller.setGame(game);
  (window as unknown as { __controller: Controller; __game: Fff }).__controller =
    controller;
  (window as unknown as { __game: Fff }).__game = game;

  controller.onEvent = (text) => {
    eventLine.textContent = text;
  };

  worker.addEventListener("message", (ev: MessageEvent<FromWorker>) => {
    const msg = ev.data;
    if (msg.kind === "progress") {
      note.textContent = msg.note;
      bar.style.width = `${Math.round((msg.loaded ?? 0) * 100)}%`;
    } else if (msg.kind === "ready") {
      loading.style.display = "none";
    } else if (msg.kind === "error") {
      loading.style.display = "grid";
      note.textContent = `could not load the brain: ${msg.message}`;
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
    loomInjection: 0.4,
  };
  worker.postMessage(start);

  buildControls(game);
  explain.textContent = MODE_TEXT[game.mode];

  const fmt = (v: number, d = 1) => v.toFixed(d).padStart(6);
  const loop = () => {
    controller.frame();
    const h = controller.hud();
    const pressRate =
      h.simSeconds > 0 ? (game.pressCount / h.simSeconds) * 60 : 0;
    hud.textContent =
      `mode ${game.mode.padEnd(11)} flapper ${game.flapper.padEnd(8)} ` +
      `scene ${game.scene ? "on " : "off"}\n` +
      `score ${String(game.score).padStart(3)}   best ${String(game.best).padStart(3)}   ` +
      `alive ${fmt(game.bestSurvived)}s best   presses ${String(game.pressCount).padStart(3)} ` +
      `(${pressRate.toFixed(1)}/min of sim time)\n` +
      `sim ${fmt(h.simSpeed, 2)}x   ${fmt(h.spikesPerSecond / 1000)}k spikes/s   ` +
      `threat ${fmt(h.threat, 2)}   ${h.state}\n` +
      ["GF", "DNa02_L", "DNa02_R", "descending"]
        .map((k) => `${k} ${fmt(h.rates[k] ?? 0)}Hz`)
        .join("   ");
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function buildControls(game: Fff): void {
  controls.replaceChildren();

  const group = (label: string, nodes: HTMLElement[]) => {
    const wrap = document.createElement("div");
    wrap.className = "group";
    const l = document.createElement("span");
    l.className = "label";
    l.textContent = label;
    wrap.append(l, ...nodes);
    controls.append(wrap);
  };

  const toggle = <T extends string>(
    values: readonly T[],
    get: () => T,
    set: (v: T) => void,
  ) =>
    values.map((v) => {
      const b = document.createElement("button");
      b.textContent = v;
      const paint = () => b.classList.toggle("on", get() === v);
      b.addEventListener("click", () => {
        const before = game.mode;
        set(v);
        explain.textContent = MODE_TEXT[game.mode];
        if (game.mode !== before) buildControls(game);
        else {
          controls
            .querySelectorAll("button")
            .forEach((x) => x.dispatchEvent(new Event("repaint")));
        }
      });
      b.addEventListener("repaint", paint);
      paint();
      return b;
    });

  group(
    "mode",
    toggle<FffMode>(
      ["controller", "pilot"],
      () => game.mode,
      (v) => game.setMode(v),
    ),
  );
  group(
    "flapper",
    toggle<Flapper>(
      ["fly", "poisson", "nobody"],
      () => game.flapper,
      (v) => {
        game.flapper = v;
        game.reset();
      },
    ),
  );
  // Only offered in pilot mode, where the fly is among the pipes and the
  // control does something. In controller mode the chamber sits behind
  // the bird, so the fly only ever sees a pipe on its way out — measured
  // at 5.83 Hz of descending drive against 5.77 with the pipes hidden
  // from it, and 73 presses a minute against 74. A switch that changes
  // nothing is worse than no switch: it implies a coupling that is not
  // there.
  if (game.mode === "pilot") {
    group(
      "pipes in the fly's eyes",
      toggle(
        ["on", "off"] as const,
        () => (game.scene ? "on" : "off"),
        (v) => {
          game.scene = v === "on";
        },
      ),
    );
  }
}

main();
