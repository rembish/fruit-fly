"""fruitfly — a desktop fly driven by the real Drosophila connectome.

A leaky integrate-and-fire simulation of the complete FlyWire adult fly brain
(~139k neurons, ~50M synapses) runs in a background thread. Your mouse cursor
is fed into the fly's looming-detector neurons, the screen into its
photoreceptors, and the spiking of its real descending neurons (giant fiber,
DNa02 steering neurons, ...) moves a fly sprite around your desktop.
"""

import sys

if sys.version_info < (3, 10):                      # noqa: UP036
    raise SystemExit(
        f"fruitfly needs Python 3.10 or newer, but this is "
        f"{sys.version.split()[0]} at {sys.executable}\n"
        f"On macOS `python3` is often Xcode's bundled 3.9, which cannot "
        f"install this project's dependencies: pyobjc-core has no wheel "
        f"for 3.9 and the fallback source build fails on recent clang.\n"
        f"Install a current Python (`brew install python@3.13`) and use "
        f"that interpreter, ideally in a venv.")

__version__ = "0.2.0"

DATA_URL = "https://storage.googleapis.com/flywire-data/codex/data/fafb/783"
DATA_FILES = [
    "connections.csv.gz",
    "classification.csv.gz",
    "neurons.csv.gz",
    "consolidated_cell_types.csv.gz",
    "column_assignment.csv.gz",
]
