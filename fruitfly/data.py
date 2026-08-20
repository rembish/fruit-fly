"""Download and preprocess the FlyWire connectome into compact arrays.

Produces data/brain.npz containing:
  - CSR connectivity (indptr, indices, weights) over neuron indices
  - weights = signed synapse counts (sign from predicted neurotransmitter)
  - named neuron populations used for sensory input and motor readout
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import urllib.request

import numpy as np

from . import DATA_URL, DATA_FILES

# Neurotransmitter sign convention (Shiu et al. 2024): acetylcholine
# excitatory; GABA and glutamate inhibitory (GluCl channels in fly);
# monoamines treated as excitatory.
NT_SIGN = {
    "ACH": +1.0, "GABA": -1.0, "GLUT": -1.0,
    "DA": +1.0, "OCT": +1.0, "SER": +1.0,
}

# Populations we care about, selected from the classification table.
# (name, column, values)
POPULATIONS = [
    # sensory inputs
    ("photoreceptor", "cell_type", {"R1-6", "R7", "R8"}),
    ("LC4", "cell_type", {"LC4"}),        # looming detectors -> giant fiber
    ("LPLC2", "cell_type", {"LPLC2"}),    # looming detectors -> giant fiber
    ("LC6", "cell_type", {"LC6"}),        # looming / escape related
    ("JO", "cell_type", None),            # handled specially below (antennal)
    # motor readouts
    ("GF", "cell_type", {"DNp01"}),       # giant fiber: escape command
    ("DNa02", "cell_type", {"DNa02"}),    # steering descending neuron
    ("DNa01", "cell_type", {"DNa01"}),    # steering descending neuron
    ("DNp09", "cell_type", {"DNp09"}),    # forward locomotion command
    ("MDN", "cell_type", {"MDN"}),        # backward locomotion command
    ("descending", "super_class", {"descending"}),
]


def data_dir(root: str | None = None) -> str:
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data")


def fetch(root: str | None = None) -> None:
    d = data_dir(root)
    os.makedirs(d, exist_ok=True)
    for f in DATA_FILES:
        path = os.path.join(d, f)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print(f"[fetch] {f} already present")
            continue
        print(f"[fetch] downloading {f} ...")
        urllib.request.urlretrieve(f"{DATA_URL}/{f}", path)
        print(f"[fetch] {f}: {os.path.getsize(path) / 1e6:.1f} MB")


def _read_csv_gz(path: str, usecols: list[str]) -> dict[str, np.ndarray]:
    """Minimal streaming CSV reader (files are simple, comma-separated)."""
    import csv

    out: dict[str, list] = {c: [] for c in usecols}
    with gzip.open(path, "rt", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        idx = {c: header.index(c) for c in usecols}
        for row in reader:
            for c in usecols:
                out[c].append(row[idx[c]])
    return {c: np.asarray(v) for c, v in out.items()}


def prepare(root: str | None = None, min_synapses: int = 5) -> str:
    """Build data/brain.npz from the raw Codex tables."""
    d = data_dir(root)
    out_path = os.path.join(d, "brain.npz")

    print("[prepare] reading classification ...")
    cls = _read_csv_gz(
        os.path.join(d, "classification.csv.gz"),
        ["root_id", "flow", "super_class", "class", "side"],
    )
    root_ids = cls["root_id"].astype(np.int64)
    n = len(root_ids)
    print(f"[prepare] {n} classified neurons")

    # cell type names live in a separate consolidated table
    ct = _read_csv_gz(
        os.path.join(d, "consolidated_cell_types.csv.gz"),
        ["root_id", "primary_type"],
    )
    ct_map = dict(zip(ct["root_id"].astype(np.int64).tolist(),
                      ct["primary_type"].tolist()))
    cls["cell_type"] = np.asarray([ct_map.get(r, "") for r in root_ids.tolist()])

    print("[prepare] reading connections (this is the big one) ...")
    con = _read_csv_gz(
        os.path.join(d, "connections.csv.gz"),
        ["pre_root_id", "post_root_id", "syn_count", "nt_type"],
    )
    pre_raw = con["pre_root_id"].astype(np.int64)
    post_raw = con["post_root_id"].astype(np.int64)
    syn = con["syn_count"].astype(np.int64)
    nt = con["nt_type"]
    del con

    # map root ids -> dense indices, dropping neurons missing classification
    print("[prepare] indexing ...")
    sorter = np.argsort(root_ids)
    sorted_ids = root_ids[sorter]

    def to_index(ids: np.ndarray) -> np.ndarray:
        pos = np.searchsorted(sorted_ids, ids)
        pos = np.clip(pos, 0, n - 1)
        ok = sorted_ids[pos] == ids
        res = np.where(ok, sorter[pos], -1)
        return res

    pre = to_index(pre_raw)
    post = to_index(post_raw)
    keep = (pre >= 0) & (post >= 0)
    pre, post, syn, nt = pre[keep], post[keep], syn[keep], nt[keep]

    # aggregate across neuropils: sum synapses per (pre, post) pair
    print("[prepare] aggregating per neuron pair ...")
    sign = np.array([NT_SIGN.get(t, +1.0) for t in nt.tolist()], dtype=np.float32)
    signed = syn.astype(np.float32) * sign
    key = pre.astype(np.int64) * n + post.astype(np.int64)
    order = np.argsort(key, kind="stable")
    key, signed, syn = key[order], signed[order], syn[order]
    boundaries = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(key)]))
    seg_sum = np.add.reduceat(signed, starts)
    seg_syn = np.add.reduceat(syn, starts)
    ukey = key[starts]
    upre = (ukey // n).astype(np.int32)
    upost = (ukey % n).astype(np.int32)

    strong = seg_syn >= min_synapses
    upre, upost, w = upre[strong], upost[strong], seg_sum[strong]
    print(f"[prepare] {strong.sum()} connections with >= {min_synapses} synapses "
          f"({int(seg_syn[strong].sum())} synapses total)")
    del key, signed, syn, seg_sum, seg_syn, ukey, ends

    # CSR by presynaptic neuron
    order = np.argsort(upre, kind="stable")
    upre, upost, w = upre[order], upost[order], w[order]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, upre + 1, 1)
    indptr = np.cumsum(indptr)

    # named populations
    pops: dict[str, np.ndarray] = {}
    side = cls["side"]
    for name, col, values in POPULATIONS:
        if name == "JO":  # Johnston's organ (antennal mechanosensors)
            mask = np.char.startswith(cls["cell_type"].astype(str), "JO-")
        else:
            mask = np.isin(cls[col], list(values))
        for s in ("left", "right"):
            key_name = f"{name}_{s[0].upper()}"
            pops[key_name] = np.flatnonzero(mask & (side == s)).astype(np.int32)
        pops[name] = np.flatnonzero(mask).astype(np.int32)
        print(f"[prepare] population {name}: {int(mask.sum())} neurons "
              f"(L {len(pops[name + '_L'])} / R {len(pops[name + '_R'])})")

    central = np.isin(cls["super_class"], ["central"])
    pops["central"] = np.flatnonzero(central).astype(np.int32)

    np.savez_compressed(
        out_path,
        indptr=indptr,
        indices=upost.astype(np.int32),
        weights=w.astype(np.float32),
        root_ids=root_ids,
        **{f"pop_{k}": v for k, v in pops.items()},
    )
    meta = {
        "n_neurons": int(n),
        "n_connections": int(len(upost)),
        "n_synapses": int(np.abs(w).sum()),
        "min_synapses": min_synapses,
        "populations": {k: int(len(v)) for k, v in pops.items()},
    }
    with open(os.path.join(d, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[prepare] wrote {out_path} ({os.path.getsize(out_path)/1e6:.1f} MB)")
    return out_path


def load(root: str | None = None):
    """Load the prepared brain. Returns (indptr, indices, weights, pops)."""
    path = os.path.join(data_dir(root), "brain.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found — run `python -m fruitfly fetch` then "
            f"`python -m fruitfly prepare` first."
        )
    z = np.load(path)
    pops = {k[4:]: z[k] for k in z.files if k.startswith("pop_")}
    return z["indptr"], z["indices"], z["weights"], pops


if __name__ == "__main__":
    fetch()
    prepare()
