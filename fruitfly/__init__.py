"""fruitfly — a desktop fly driven by the real Drosophila connectome.

A leaky integrate-and-fire simulation of the complete FlyWire adult fly brain
(~139k neurons, ~50M synapses) runs in a background thread. Your mouse cursor
is fed into the fly's looming-detector neurons, the screen into its
photoreceptors, and the spiking of its real descending neurons (giant fiber,
DNa02 steering neurons, ...) moves a fly sprite around your desktop.
"""

__version__ = "0.1.0"

DATA_URL = "https://storage.googleapis.com/flywire-data/codex/data/fafb/783"
DATA_FILES = [
    "connections.csv.gz",
    "classification.csv.gz",
    "neurons.csv.gz",
    "consolidated_cell_types.csv.gz",
]
