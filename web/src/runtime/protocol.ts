/**
 * What crosses the worker boundary, and in which direction.
 *
 * The split mirrors the desktop's: a brain thread that does nothing but
 * sense and step, and a controller that owns the body, the world and the
 * screen. The one difference is that `senses` lives on the *worker* side
 * here. On the desktop the controller computes stimuli and hands over a
 * list; doing that across a `postMessage` would serialise several
 * thousand per-neuron rates every frame, so instead the raw eye patches
 * go over — two 96x96 Float32Arrays, transferred rather than copied —
 * and the worker turns them into drive.
 */

/** Eye patches and where the fly was when they were sampled. */
export interface SenseMessage {
  kind: "sense";
  /** PATCH*PATCH luminance in [0, 1], or null when the fly is blind. */
  patchL: Float32Array | null;
  patchR: Float32Array | null;
  /** Simulated seconds since the previous patches. */
  patchDt: number;
  flyX: number;
  flyY: number;
  heading: number;
  cursorX: number;
  cursorY: number;
}

/** Drive one real population by name — the poke panel, and swats. */
export interface PokeMessage {
  kind: "poke";
  pop: string;
  hz: number;
  /** Simulated seconds to hold it for. */
  seconds: number;
}

export interface ControlMessage {
  kind: "control";
  /** Fresh dynamical state, same anatomy: a new fly's brain. */
  reset?: boolean;
  /** Pause stepping without tearing the worker down. */
  running?: boolean;
}

export interface StartMessage {
  kind: "start";
  brainUrl: string;
  seed: number;
  noiseRate: number;
  noiseWeight: number;
  inhGain: number;
  dt: number;
  /** 0 disables the direct LC4/LPLC2 injection: pure retina. */
  loomInjection: number;
}

export type ToWorker =
  | StartMessage
  | SenseMessage
  | PokeMessage
  | ControlMessage;

export interface ReadyMessage {
  kind: "ready";
  neurons: number;
  connections: number;
  attribution: string;
  /** Population names the poke panel may drive. */
  pops: string[];
}

export interface ProgressMessage {
  kind: "progress";
  /** 0..1, or null while the size is unknown. */
  loaded: number | null;
  note: string;
}

/**
 * One chunk of simulated time, reported.
 *
 * `simTimeMs` is the authority for everything downstream — the body, the
 * world, the retina cadence. The main thread advances by the *delta* of
 * this number and never by its own clock, which is what makes a slow
 * machine run in honest slow motion instead of quietly breaking the
 * motor calibration.
 */
export interface TickMessage {
  kind: "tick";
  simTimeMs: number;
  rates: Record<string, number>;
  /** Giant fiber spikes since the last tick. */
  gfCount: number;
  threat: number;
  bearing: number;
  /** Diagnostics for the HUD; never an input to anything. */
  simSpeed: number;
  spikesPerSecond: number;
}

export interface ErrorMessage {
  kind: "error";
  message: string;
}

export type FromWorker =
  | ReadyMessage
  | ProgressMessage
  | TickMessage
  | ErrorMessage;
