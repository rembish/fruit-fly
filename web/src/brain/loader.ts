/**
 * Read `brain.bin` — the container `fruitfly/export_web.py` writes.
 *
 * Layout: magic, a uint32 header length, a JSON directory of named
 * sections, then the raw little-endian arrays, each padded to 8 bytes.
 * Views are built directly on the incoming ArrayBuffer with no copying,
 * which is the entire reason the exporter aligns the sections: a
 * TypedArray on a misaligned offset does not degrade, it throws.
 */

const MAGIC = "FFLYBRN\0";

export interface BrainSection {
  name: string;
  dtype: string;
  offset: number;
  count: number;
  shape: number[];
}

export interface BrainHeader {
  format: number;
  n_neurons: number;
  n_connections: number;
  n_synapses: number;
  attribution: string;
  sections: BrainSection[];
}

export interface BrainData {
  header: BrainHeader;
  indptr: Int32Array;
  indices: Int32Array;
  weights: Int16Array;
  /** Population name -> neuron indices, the same names `brain.py` uses. */
  pops: Map<string, Int32Array>;
  /** Retinotopy, for Phase 2; carried now so the format needs no bump. */
  retina: Map<string, Int32Array | Float32Array>;
}

/** The format this reader understands. A newer file is an error, not a guess. */
export const SUPPORTED_FORMAT = 1;

function view(
  buf: ArrayBuffer,
  base: number,
  s: BrainSection,
): Int32Array | Int16Array | Float32Array {
  const at = base + s.offset;
  switch (s.dtype) {
    case "<i4":
      return new Int32Array(buf, at, s.count);
    case "<i2":
      return new Int16Array(buf, at, s.count);
    case "<f4":
      return new Float32Array(buf, at, s.count);
    default:
      throw new Error(`brain.bin: unknown section dtype ${s.dtype}`);
  }
}

export function parseBrain(buf: ArrayBuffer): BrainData {
  const bytes = new Uint8Array(buf);
  const magic = new TextDecoder().decode(bytes.subarray(0, MAGIC.length));
  if (magic !== MAGIC) throw new Error("not a brain.bin");

  const dv = new DataView(buf);
  const headerLen = dv.getUint32(MAGIC.length, true);
  const headerStart = MAGIC.length + 4;
  const header = JSON.parse(
    new TextDecoder().decode(
      bytes.subarray(headerStart, headerStart + headerLen),
    ),
  ) as BrainHeader;

  if (header.format !== SUPPORTED_FORMAT) {
    throw new Error(
      `brain.bin is format ${header.format}, this build reads ${SUPPORTED_FORMAT}`,
    );
  }

  // Section offsets are relative to the first 8-byte boundary after the
  // header, which is where the exporter starts writing payload.
  const base = (headerStart + headerLen + 7) & ~7;

  let indptr: Int32Array | undefined;
  let indices: Int32Array | undefined;
  let weights: Int16Array | undefined;
  const pops = new Map<string, Int32Array>();
  const retina = new Map<string, Int32Array | Float32Array>();

  for (const s of header.sections) {
    const arr = view(buf, base, s);
    if (s.name === "indptr") indptr = arr as Int32Array;
    else if (s.name === "indices") indices = arr as Int32Array;
    else if (s.name === "weights") weights = arr as Int16Array;
    else if (s.name.startsWith("pop_"))
      pops.set(s.name.slice(4), arr as Int32Array);
    else if (s.name.startsWith("retina_"))
      retina.set(s.name.slice(7), arr as Int32Array | Float32Array);
  }

  if (!indptr || !indices || !weights) {
    throw new Error("brain.bin is missing indptr, indices or weights");
  }
  if (indptr.length - 1 !== header.n_neurons) {
    throw new Error("brain.bin: indptr length disagrees with n_neurons");
  }
  return { header, indptr, indices, weights, pops, retina };
}
