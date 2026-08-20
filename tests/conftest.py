"""Wiring so one `pytest` runs every suite in here.

Three of these files were written as scripts, because their output is a
narrative worth reading — 30 seconds of a fly's life, or a retina lighting
up — and they need the compiled connectome, which a fresh clone does not
have. That kept them out of `pytest` entirely, so "tests pass" quietly
meant "a quarter of the tests pass".

Rather than importing pytest into those scripts, which would stop them
being runnable on their own, the marking happens here: the three entry
points get a `slow` marker, and everything that loads the connectome --
including six fast checks in test_backends.py, which build a Controller
and so need a brain -- is skipped with a clear reason when
data/brain.npz is absent, rather than failing on a clean checkout.

    pytest                  # everything
    pytest -m "not slow"    # just the fast checks
"""

import pathlib

import pytest

#: Everything that loads data/brain.npz, which a fresh clone lacks. The
#: fast ones are here too: they build a Controller, which needs a brain,
#: and without this they failed rather than skipped on a clean checkout.
NEEDS_CONNECTOME = {
    "test_blind_host_survives",
    "test_brain_smoke",
    "test_closed_loop_behaviour",
    "test_controller_loop",
    "test_drawing_surfaces",
    "test_grab_bounds_at_screen_edges",
    "test_hit_radius",
    "test_retina_and_looming",
    "test_swat_semantics",
}

#: The subset that also takes tens of seconds, so it can be deselected.
SLOW = {
    "test_brain_smoke",
    "test_closed_loop_behaviour",
    "test_retina_and_looming",
}

_BRAIN = pathlib.Path(__file__).resolve().parent.parent / "data" / "brain.npz"


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    # `config` is unused but pytest injects hook arguments by name,
    # so it cannot be renamed to _config to quiet the linter.
    skip = pytest.mark.skip(
        reason=f"no compiled connectome at {_BRAIN} — run "
               f"`python3 -m fruitfly prepare` first")
    have_brain = _BRAIN.exists()
    for item in items:
        if item.name in SLOW:
            item.add_marker(pytest.mark.slow)
        if item.name in NEEDS_CONNECTOME and not have_brain:
            item.add_marker(skip)
