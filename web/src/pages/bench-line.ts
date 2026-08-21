/**
 * The benchmark's numbers, rendered wherever a page asks for them.
 *
 * The design doc wants these on the page, and for a reason worth
 * keeping in view: the score in the corner of a running game is
 * theatre, and this is the result. Shared between the hub and the
 * cabinet so the two cannot drift into quoting different figures.
 *
 * Silent when `bench.json` is absent. It is a build artefact produced by
 * `npm run bench`, and a blank line is better than a stale one.
 */

export interface BenchReport {
  roundsPerArm: number;
  flyBeatsPoisson: number;
  flyBeatsNobody: number;
  escapesOntoPlate: number;
  startles: number;
  gameIsWinnable?: boolean;
  seeds?: number[];
  arms: Record<string, { medianScore: number; scoreCI: [number, number] }>;
}

export function formatBench(b: BenchReport): string {
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const arm = (k: string) => {
    const a = b.arms[k];
    if (!a) return "—";
    return `${a.medianScore} (95% CI ${a.scoreCI[0]}–${a.scoreCI[1]})`;
  };
  const seeds = b.seeds?.length ? `, ${b.seeds.length} seeds` : "";
  return (
    `Median pipes cleared, over ${b.roundsPerArm} rounds per arm${seeds}:\n` +
    `  the fly ${arm("fly")}        a coin at the fly's own rate ${arm("poisson")}\n` +
    `  nobody ${arm("nobody")}        a control that can see the gap ${arm("oracle")}\n` +
    `The fly beats its rate-matched control in ${pct(b.flyBeatsPoisson)} of rounds — ` +
    `50% is chance — and beats doing nothing in ${pct(b.flyBeatsNobody)}.\n` +
    `It startled ${b.startles} times; ${b.escapesOntoPlate} of those ` +
    `(${pct(b.escapesOntoPlate / Math.max(1, b.startles))}) ended on the plate, ` +
    `so most of its button presses are accidents.`
  );
}

export async function showBench(elementId = "bench"): Promise<void> {
  const el = document.getElementById(elementId);
  if (!el) return;
  try {
    const res = await fetch("/brain/bench.json");
    if (!res.ok) return;
    el.textContent = formatBench((await res.json()) as BenchReport);
  } catch {
    // Nothing to show, and nothing worth putting on screen about it.
  }
}
