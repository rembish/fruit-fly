/**
 * The fly, and the splat when you get it. Canvas 2D, no assets.
 *
 * A simplified read of `fruitfly/sprite.py`: same anatomy, same wingbeat
 * blur trick. Everything is drawn in a body-length unit so one `size`
 * argument scales the whole animal.
 */

export interface FlyLook {
  size: number;
  heading: number;
  flying: boolean;
  escaping: boolean;
  wingPhase: number;
}

export function drawFly(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  look: FlyLook,
): void {
  const { size, heading, flying, escaping, wingPhase } = look;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(heading);
  const u = size / 34; // the desktop's default body length

  // Wings first, so the body sits on top of them. A real wingbeat is
  // ~200 Hz and no display can show it, so what is drawn is the blur:
  // two translucent ellipses whose spread breathes with the phase.
  if (flying) {
    const spread = 0.55 + 0.45 * Math.abs(Math.sin(wingPhase));
    ctx.globalAlpha = 0.32;
    ctx.fillStyle = "#dfe9f5";
    for (const side of [-1, 1]) {
      ctx.save();
      ctx.rotate(side * (0.5 + 0.35 * spread));
      ctx.beginPath();
      ctx.ellipse(2 * u, side * 9 * u, 15 * u, 5.5 * u, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    ctx.globalAlpha = 1;
  }

  // Abdomen, thorax, head — one dark body with a warm sheen.
  const body = ctx.createLinearGradient(-14 * u, 0, 14 * u, 0);
  body.addColorStop(0, "#20242b");
  body.addColorStop(0.6, "#33383f");
  body.addColorStop(1, "#171a1f");
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.ellipse(-7 * u, 0, 11 * u, 6.5 * u, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(4 * u, 0, 7.5 * u, 5.5 * u, 0, 0, Math.PI * 2);
  ctx.fill();

  // Head and the famous red eyes.
  ctx.fillStyle = "#15181c";
  ctx.beginPath();
  ctx.ellipse(12 * u, 0, 4.5 * u, 4.2 * u, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = escaping ? "#ff5a4a" : "#c0392b";
  for (const side of [-1, 1]) {
    ctx.beginPath();
    ctx.ellipse(13 * u, side * 2.6 * u, 2.6 * u, 2.4 * u, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // Legs, only worth drawing when they are doing something.
  if (!flying) {
    ctx.strokeStyle = "#1b1e23";
    ctx.lineWidth = 1.2 * u;
    for (const side of [-1, 1]) {
      for (const [ox, oy] of [
        [6, 4],
        [0, 5],
        [-6, 4.5],
      ] as const) {
        ctx.beginPath();
        ctx.moveTo(ox * u, side * oy * u);
        ctx.lineTo((ox - 3) * u, side * (oy + 5) * u);
        ctx.stroke();
      }
    }
  }
  ctx.restore();
}

export function drawSplat(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  heading: number,
  size: number,
): void {
  const u = size / 34;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(heading);
  ctx.fillStyle = "rgba(120, 30, 28, 0.85)";
  ctx.beginPath();
  ctx.ellipse(0, 0, 13 * u, 9 * u, 0, 0, Math.PI * 2);
  ctx.fill();
  // Spatter: deterministic offsets, so a splat does not shimmer as it
  // is redrawn every frame.
  const bits: readonly (readonly [number, number, number])[] = [
    [10, -8, 2.5],
    [-11, 7, 3],
    [4, 12, 2],
    [-8, -10, 1.8],
    [14, 4, 1.6],
  ];
  for (const [bx, by, br] of bits) {
    ctx.beginPath();
    ctx.arc(bx * u, by * u, br * u, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}
