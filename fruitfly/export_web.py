"""Ship the compiled brain to the browser, and the numbers that prove the
port agrees with this one.

`docs/web-plan.md` Phase 1. Two artefacts:

**brain.bin** — the anatomy, in a self-describing container. A magic, a
JSON directory of named sections, then the raw little-endian arrays. The
directory rather than a fixed struct because the section list grows (the
retina arrays are here for Phase 2 already, so that phase does not need
a format bump), and because a TypedArray view is only as safe as the
offset it is built on: every section is padded to 8 bytes, which every
alignment a browser can ask for divides into. Misaligned offsets do not
degrade in JavaScript, they throw.

The wire dtypes are narrower than the Python ones and each narrowing is
asserted at export rather than trusted:

  - `indptr` int64 -> int32. 2.7 M connections against a 2.1 G ceiling.
  - `indices` int32 as-is. 139,255 neurons will not fit in int16.
  - `weights` float32 -> int16 signed synapse counts, which is what they
    have always been: whole numbers in [-2405, 1897]. The exc/inh gains
    and the PSP calibration are applied at load time on both sides, so
    the file stays the anatomy and the tuning stays in the code.

**parity.json** — a seeded Python run's per-population mean rates, which
is what the TypeScript port is held to. Rates rather than spike counts,
and means over whole populations rather than spike times, because the
two runtimes will never agree spike-for-spike: they cannot share a
random number generator, and a Poisson-driven recurrent network diverges
from any difference at all. Statistical parity is the goal and
spike-exact parity is explicitly not.

  The tolerance is measured, not chosen. Several seeds of the *same*
  Python model are run, and the tolerance for each population is a
  multiple of the spread across them: whatever a population's number
  does between two runs of the reference implementation is what the port
  cannot be blamed for. Small populations need this most — GF is two
  neurons, and two neurons are noisy — which is also why the seed count
  is five rather than the two the plan first said. A spread estimated
  from one degree of freedom can come out near zero by luck, and then
  the gate is one no implementation could pass, including this one.
"""

from __future__ import annotations

import json
import os
import struct

import numpy as np

from .brain import Brain, Params, _psp_calibration

#: Bumped only when the layout changes in a way a reader must notice.
FORMAT_MAGIC = b"FFLYBRN\x00"
FORMAT_VERSION = 1

#: Every section starts here. 8 rather than 4 because it costs a handful
#: of bytes and removes the whole class of bug.
ALIGN = 8

#: Wire dtype per section family. numpy names are already the DataView
#: vocabulary, so they travel as-is.
WIRE = {"indptr": "<i4", "indices": "<i4", "weights": "<i2"}

ATTRIBUTION = (
    "FlyWire whole-brain connectome, snapshot 783 (Dorkenwald et al. "
    "2024; Schlegel et al. 2024), with column assignments from Matsliah "
    "et al. 2024. Licensed CC BY-NC 4.0."
)

#: What the parity gate watches. The small ones are here because they
#: are what the fly is steered by, not because they measure well.
PARITY_POPS = ["GF", "DNa02_L", "DNa02_R", "DNa01", "DNp09", "MDN",
               "descending", "LC4", "LPLC2", "central"]

#: Long enough that a two-neuron population has fired often enough to
#: have a rate at all.
PARITY_SECONDS = 60.0
PARITY_SEEDS = (7, 11, 13, 17, 19)

#: An effect the port must clear... in reverse: how far the port may sit
#: from the Python mean before it counts as a different model. One and a
#: half times what the reference does to itself between seeds.
PARITY_MARGIN = 1.5


def _wire_arrays(indptr, indices, weights, pops, retina) -> dict:
    """Every array in its wire dtype, with the narrowings checked."""
    out: dict[str, np.ndarray] = {}

    total = int(indptr[-1])
    assert total <= np.iinfo(np.int32).max, f"{total} connections > int32"
    out["indptr"] = np.asarray(indptr, dtype=np.int32)

    assert int(np.max(indices)) <= np.iinfo(np.int32).max
    out["indices"] = np.asarray(indices, dtype=np.int32)

    w = np.asarray(weights)
    assert np.all(w == np.round(w)), "weights are whole synapse counts"
    peak = int(np.max(np.abs(w)))
    assert peak <= np.iinfo(np.int16).max, (
        f"|weight| reaches {peak}: widen the wire dtype to int32 and bump "
        f"FORMAT_VERSION")
    out["weights"] = w.astype(np.int16)

    for name, v in pops.items():
        out[f"pop_{name}"] = np.asarray(v, dtype=np.int32)
    for name, raw in retina.items():
        v = np.asarray(raw)
        out[f"retina_{name}"] = (v.astype(np.float32) if v.dtype.kind == "f"
                                 else v.astype(np.int32))
    return out


def _pad(n: int) -> int:
    return (-n) % ALIGN


def write_brain(path: str, indptr, indices, weights, pops, retina) -> dict:
    """Write brain.bin; return the header that describes it."""
    arrays = _wire_arrays(indptr, indices, weights, pops, retina)

    sections, offset = [], 0
    for name, arr in arrays.items():
        offset += _pad(offset)
        sections.append({
            "name": name,
            "dtype": arr.dtype.str,          # '<i4', '<i2', '<f4'
            "offset": offset,
            "count": int(arr.size),
            "shape": list(arr.shape),
        })
        offset += arr.nbytes
    payload_bytes = offset

    header = {
        "format": FORMAT_VERSION,
        "n_neurons": len(arrays["indptr"]) - 1,
        "n_connections": int(arrays["indices"].size),
        "n_synapses": int(np.abs(np.asarray(weights)).sum()),
        "attribution": ATTRIBUTION,
        "sections": sections,
    }
    blob = json.dumps(header, separators=(",", ":")).encode()
    # The data offsets above are relative to the end of the header, and
    # the header's own length changes nothing about them.
    with open(path, "wb") as fh:
        fh.write(FORMAT_MAGIC)
        fh.write(struct.pack("<I", len(blob)))
        fh.write(blob)
        start = fh.tell()
        fh.write(b"\0" * _pad(start))
        written = 0
        for arr in arrays.values():
            fh.write(b"\0" * _pad(written))
            written += _pad(written)
            fh.write(np.ascontiguousarray(arr).tobytes())
            written += arr.nbytes
        assert written == payload_bytes, (written, payload_bytes)
    return header


def read_brain(path: str) -> tuple[dict, dict]:
    """Read brain.bin back. Exists so the exporter can be checked against
    `data.load()` rather than believed."""
    with open(path, "rb") as fh:
        raw = fh.read()
    assert raw[:len(FORMAT_MAGIC)] == FORMAT_MAGIC, "not a brain.bin"
    pos = len(FORMAT_MAGIC)
    (hdr_len,) = struct.unpack_from("<I", raw, pos)
    pos += 4
    header = json.loads(raw[pos:pos + hdr_len])
    pos += hdr_len
    pos += _pad(pos)
    arrays = {}
    for s in header["sections"]:
        a = np.frombuffer(raw, dtype=np.dtype(s["dtype"]),
                          count=s["count"], offset=pos + s["offset"])
        arrays[s["name"]] = a.reshape(s["shape"])
    return header, arrays


def parity_reference(indptr, indices, weights, pops, *, dt=2.0,
                     seconds=PARITY_SECONDS, seeds=PARITY_SEEDS,
                     noise_rate=100.0, noise_weight=3.0,
                     inh_gain=1.5) -> dict:
    """Run the reference brain several times; return what the port must
    reproduce, and how far it may miss by.

    No stimulus and no retina: this is the network's own resting
    behaviour, which is the part the port either gets right or does not.
    Sensory drive is Phase 2's problem and would only add a second thing
    that could be wrong.
    """
    steps = int(round(seconds * 1000.0 / dt))
    runs = []
    for seed in seeds:
        brain = Brain(indptr, indices, weights, pops, dt=dt,
                      noise_rate=noise_rate, noise_weight=noise_weight,
                      inh_gain=inh_gain, seed=seed)
        counts = dict.fromkeys(PARITY_POPS, 0)
        masks = {k: np.zeros(brain.n, dtype=bool) for k in PARITY_POPS}
        for k in PARITY_POPS:
            masks[k][pops[k]] = True
        total = 0
        for _ in range(steps):
            spiked = brain.step()
            if len(spiked):
                total += len(spiked)
                for k in PARITY_POPS:
                    counts[k] += int(masks[k][spiked].sum())
        runs.append({
            "seed": seed,
            "total_spikes": total,
            "network_hz": total / (brain.n * seconds),
            # Where the noise governor ended up. It is part of the model
            # and it is a feedback loop, so it is worth comparing on its
            # own: a port whose rates matched by luck would still show a
            # governor sitting somewhere else. Expect zero — see the
            # note on `network_hz` below.
            "noise_rate_final": float(brain.noise_rate),
            "rates": {k: counts[k] / (len(pops[k]) * seconds)
                      for k in PARITY_POPS},
        })

    def spread(values):
        return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0

    rates = {k: [r["rates"][k] for r in runs] for k in PARITY_POPS}
    net = [r["network_hz"] for r in runs]
    gov = [r["noise_rate_final"] for r in runs]
    return {
        "seconds": seconds,
        "dt": dt,
        "noise_rate": noise_rate,
        "noise_weight": noise_weight,
        "inh_gain": inh_gain,
        "seeds": list(seeds),
        "margin": PARITY_MARGIN,
        # The port recomputes this from dt and must land on the same
        # number; it is the one constant both runtimes derive rather
        # than read, so it is the one most able to drift apart.
        "psp_unit_weight": _psp_calibration(dt, Params()),
        "network_hz": {"mean": float(np.mean(net)), "sd": spread(net),
                       "tolerance": PARITY_MARGIN * spread(net),
                       "per_seed": net},
        # The plan expected this to sit at the governor's own 1.0 target.
        # It does not, and the reason is worth writing down rather than
        # tuning away: the governor's only lever is *adding* noise. This
        # network is already above target on its own recurrence, so the
        # loop drives the floor to zero within about ten seconds and then
        # has nothing left to do. The governor prevents coma; it cannot
        # prevent liveliness. The gate compares the port against this
        # measured number, not against the target the model aims at.
        "noise_rate_final": {"mean": float(np.mean(gov)),
                             "sd": spread(gov),
                             "tolerance": PARITY_MARGIN * spread(gov),
                             "per_seed": gov},
        "rates": {
            k: {"mean": float(np.mean(v)), "sd": spread(v),
                "tolerance": PARITY_MARGIN * spread(v),
                "per_seed": v, "size": int(len(pops[k]))}
            for k, v in rates.items()
        },
        "runs": runs,
    }


def format_parity(ref: dict) -> str:
    lines = [f"parity reference — {len(ref['seeds'])} seeds {ref['seeds']}, "
             f"{ref['seconds']:.0f} bio-s each, dt={ref['dt']}, "
             f"noise {ref['noise_rate']:.0f} Hz, no stimulus",
             f"psp unit weight {ref['psp_unit_weight']:.9f} "
             f"(the port must derive the same to 1e-6)",
             ""]
    net = ref["network_hz"]
    lines.append(f"  {'network':14s} {'size':>7s} {'mean Hz':>9s} "
                 f"{'sd':>8s} {'tolerance':>10s}")
    lines.append(f"  {'(all)':14s} {'':>7s} {net['mean']:9.4f} "
                 f"{net['sd']:8.4f} {net['tolerance']:10.4f}")
    for k, v in ref["rates"].items():
        lines.append(f"  {k:14s} {v['size']:7d} {v['mean']:9.4f} "
                     f"{v['sd']:8.4f} {v['tolerance']:10.4f}")
    gov = ref["noise_rate_final"]
    lines.append("")
    lines.append(f"noise governor settles at {gov['mean']:.2f} Hz "
                 f"(sd {gov['sd']:.2f}) — it can only raise the floor, and "
                 f"this network is already above")
    lines.append(f"the 1.0 Hz/neuron it targets, so it empties out and the "
                 f"network holds {ref['network_hz']['mean']:.2f} on its own "
                 f"recurrence")
    lines.append("")
    lines.append("a tolerance is 1.5x what the reference does to itself "
                 "between seeds; a population whose sd is large is one "
                 "the gate cannot police, and says so here rather than "
                 "pretending otherwise")
    return "\n".join(lines)


DATA_LICENSE = """# Data license

`brain.bin` is compiled from the FlyWire whole-brain connectome,
snapshot 783, and from the eye column assignments published alongside
it.

    Dorkenwald et al. 2024, "Neuronal wiring diagram of an adult brain"
    Schlegel et al. 2024, "Whole-brain annotation and multi-connectome
      cell typing of Drosophila"
    Matsliah et al. 2024, "Neuronal parts list and wiring diagram for a
      visual system"

The FlyWire data is licensed **CC BY-NC 4.0**. This file is a derived
work and carries the same terms: attribution required, non-commercial
use only. That is why the arcade is free and carries no advertising.

The simulation code around it is this repository's own, under the
license in the repository root.
"""


def export(root: str, indptr, indices, weights, pops, retina, *,
           dt=2.0, parity=True, seeds=PARITY_SEEDS, seconds=PARITY_SECONDS,
           noise_rate=100.0, inh_gain=1.5) -> dict:
    """Write everything Phase 1 ships into `web/public/brain/`."""
    out_dir = os.path.join(root, "web", "public", "brain")
    os.makedirs(out_dir, exist_ok=True)

    bin_path = os.path.join(out_dir, "brain.bin")
    header = write_brain(bin_path, indptr, indices, weights, pops, retina)
    size_mb = os.path.getsize(bin_path) / 1e6

    with open(os.path.join(out_dir, "meta.json"), "w") as fh:
        json.dump({k: v for k, v in header.items() if k != "sections"},
                  fh, indent=2)
    with open(os.path.join(out_dir, "DATA_LICENSE.md"), "w") as fh:
        fh.write(DATA_LICENSE)

    result = {"path": bin_path, "size_mb": size_mb, "header": header}
    if parity:
        ref = parity_reference(indptr, indices, weights, pops, dt=dt,
                               seeds=seeds, seconds=seconds,
                               noise_rate=noise_rate, inh_gain=inh_gain)
        with open(os.path.join(out_dir, "parity.json"), "w") as fh:
            json.dump(ref, fh, indent=2)
        result["parity"] = ref
    return result
