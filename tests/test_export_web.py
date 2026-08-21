"""The wire format, checked on a brain small enough to read by eye.

`export_web.py` narrows three arrays on their way out — int64 indptr to
int32, float32 weights to int16 — and lays every section on an 8-byte
boundary so the browser can build TypedArray views straight onto the
downloaded buffer without copying. Both of those are silent when they go
wrong: a truncated index still parses, and a misaligned offset only
throws on the far side of a 17 MB download.

So the properties are pinned here on synthetic arrays, in milliseconds,
without the connectome — and separately checked against the real one by
`export-web` itself, which reads its own output back before it claims to
have written it.

Run:  python3 tests/test_export_web.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from fruitfly import export_web as ew


def _toy():
    """Four neurons, five connections, one of each sign."""
    indptr = np.array([0, 2, 3, 5, 5], dtype=np.int64)
    indices = np.array([1, 2, 3, 0, 2], dtype=np.int32)
    weights = np.array([12, -7, 300, -2405, 1897], dtype=np.float32)
    pops = {"GF": np.array([0], dtype=np.int32),
            "descending": np.array([0, 2, 3], dtype=np.int32),
            "central": np.array([1, 2], dtype=np.int32)}
    retina = {"L_idx": np.array([1, 2], dtype=np.int32),
              "L_xy": np.array([[0.5, -0.25], [0.0, 1.0]], dtype=np.float32)}
    return indptr, indices, weights, pops, retina


def _roundtrip(tmp, *args):
    path = os.path.join(tmp, "brain.bin")
    header = ew.write_brain(path, *args)
    back_header, arrays = ew.read_brain(path)
    return header, back_header, arrays


def test_every_array_survives_the_narrowing():
    indptr, indices, weights, pops, retina = _toy()
    with tempfile.TemporaryDirectory() as tmp:
        _, _, arrays = _roundtrip(tmp, indptr, indices, weights, pops, retina)
    assert np.array_equal(arrays["indptr"], indptr)
    assert np.array_equal(arrays["indices"], indices)
    # the weights are the point: int16 must carry them exactly, because
    # they are synapse counts and a rounded synapse count is a lie
    assert np.array_equal(arrays["weights"].astype(np.float32), weights)
    for name, v in pops.items():
        assert np.array_equal(arrays[f"pop_{name}"], v), name
    for name, v in retina.items():
        assert np.array_equal(arrays[f"retina_{name}"], v), name
    print(f"{len(pops)} populations and {len(retina)} retina arrays "
          f"survive the round trip exactly")


def test_sections_land_on_alignable_offsets():
    """A TypedArray on a misaligned offset throws in every browser, and
    it throws at the user, after the download."""
    indptr, indices, weights, pops, retina = _toy()
    with tempfile.TemporaryDirectory() as tmp:
        header, _, _ = _roundtrip(tmp, indptr, indices, weights, pops, retina)
    for s in header["sections"]:
        assert s["offset"] % ew.ALIGN == 0, s
    print(f"all {len(header['sections'])} sections on "
          f"{ew.ALIGN}-byte boundaries")


def test_shapes_are_carried_not_guessed():
    """`L_xy` is (n, 2). A reader that assumed 1-D would silently halve
    the retina."""
    indptr, indices, weights, pops, retina = _toy()
    with tempfile.TemporaryDirectory() as tmp:
        _, _, arrays = _roundtrip(tmp, indptr, indices, weights, pops, retina)
    assert arrays["retina_L_xy"].shape == (2, 2)
    print(f"retina_L_xy comes back {arrays['retina_L_xy'].shape}")


def test_a_weight_too_big_for_int16_is_refused():
    """Not rounded, not clipped, not wrapped — refused, with the fix in
    the message. Silent overflow here would be a different connectome."""
    indptr, indices, weights, pops, retina = _toy()
    weights = weights.copy()
    weights[0] = 40000.0
    with tempfile.TemporaryDirectory() as tmp, \
            pytest.raises(AssertionError, match="widen"):
        _roundtrip(tmp, indptr, indices, weights, pops, retina)
    print("a 40000-synapse connection stops the export instead of wrapping")


def test_fractional_weights_are_refused():
    """Weights are summed synapse counts. A fraction means something
    upstream has already applied a gain, and the file is supposed to be
    the anatomy with no tuning baked in."""
    indptr, indices, weights, pops, retina = _toy()
    weights = weights.copy()
    weights[1] = -7.5
    with tempfile.TemporaryDirectory() as tmp, \
            pytest.raises(AssertionError, match="whole synapse counts"):
        _roundtrip(tmp, indptr, indices, weights, pops, retina)
    print("a fractional weight stops the export")


def test_the_header_says_what_the_reader_needs():
    indptr, indices, weights, pops, retina = _toy()
    with tempfile.TemporaryDirectory() as tmp:
        header, back, _ = _roundtrip(tmp, indptr, indices, weights,
                                     pops, retina)
    assert header == back
    assert header["format"] == ew.FORMAT_VERSION
    assert header["n_neurons"] == 4
    assert header["n_connections"] == 5
    assert "CC BY-NC" in header["attribution"]
    print(f"format {header['format']}, {header['n_neurons']} neurons, "
          f"attribution carried in the file itself")


def test_a_foreign_file_is_not_mistaken_for_a_brain():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "brain.bin")
        with open(path, "wb") as fh:
            fh.write(b"PK\x03\x04 this is a zip file, actually")
        with pytest.raises(AssertionError, match="not a brain.bin"):
            ew.read_brain(path)
    print("a file that is not a brain is rejected by its magic")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nALL EXPORT FORMAT TESTS PASSED")
