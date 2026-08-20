"""Leaky integrate-and-fire simulation of the whole FlyWire connectome.

Model follows Shiu et al. 2024 ("A Drosophila computational brain model
reveals sensorimotor processing", Nature 634:210-219):

  - every classified neuron is one LIF unit
  - connection weight = summed synapse count between the pair
  - sign from the predicted neurotransmitter (ACh +, GABA/Glu -)
  - membrane time constant 20 ms, resting/reset -52 mV, threshold -45 mV,
    refractory 2.2 ms, synaptic time constant 5.5 ms, delay 1.8 ms,
    single-synapse PSP calibrated to 0.275 mV

Differences from the paper (documented, deliberate, for real-time use):
  - exponential (not alpha) synaptic kernel, calibrated to the same peak PSP
  - default dt = 2.0 ms instead of 0.1 ms (decay factors are exact,
    exp(-dt/tau), so dt costs spike-timing resolution but does not
    rescale the time constants themselves)
  - optional Poisson background noise so the brain has spontaneous activity
    (the paper's network is silent without stimulation; a real brain is not)
  - spike-frequency adaptation (biological, and it stabilizes the network:
    without it the recurrent excitation has a hard phase transition between
    total silence and runaway firing; with it, supercritical noise produces
    intermittent self-quenching bursts — the fly's spontaneous "moods")

The propagation is event-driven: per step only the outgoing rows of neurons
that actually spiked are touched, which keeps ~50M synapses tractable on a
CPU because fly brain activity is sparse.
"""

from __future__ import annotations

import math

import numpy as np


class Params:
    v_rest = -52.0      # mV
    v_reset = -52.0     # mV
    v_thresh = -45.0    # mV
    tau_m = 20.0        # ms, membrane time constant
    tau_syn = 5.5       # ms, synaptic time constant
    t_refract = 2.2     # ms
    delay = 1.8         # ms, synaptic delay
    psp_peak = 0.275    # mV, depolarization from one synapse at rest
    adapt_b = 8.0       # mV of adaptation added per spike
    tau_adapt = 500.0   # ms, adaptation decay


def _decays(dt: float, p: Params) -> tuple[float, float, float]:
    """Per-step decay factors (synapse, membrane, adaptation).

    exp(-dt/tau), not the forward-Euler (1 - dt/tau) this used to use.
    Euler does not merely add error, it silently rescales the model: at
    dt=2ms it turns tau_syn=5.5 into an effective 4.42ms (-19.5%) and
    tau_m=20 into 18.98 (-5.1%). The exact factor samples the true
    continuous exponential at any dt, so dt no longer distorts the
    kernel and only limits spike-timing resolution. It costs nothing —
    these are precomputed constants either way.
    """
    return (math.exp(-dt / p.tau_syn), math.exp(-dt / p.tau_m),
            math.exp(-dt / p.tau_adapt))


def _psp_calibration(dt: float, p: Params) -> float:
    """Weight w such that one unit-weight synaptic event peaks at psp_peak mV.

    Simulates the linear membrane response to a single synaptic impulse
    with the same integration scheme and the same decay factors used at
    runtime, then rescales. Both must stay in step: this shares _decays
    with `step` precisely so the two cannot drift apart.
    """
    decay_s, decay_m, _ = _decays(dt, p)
    s, v, peak = 1.0, 0.0, 0.0
    for _ in range(int(200 / dt)):
        v = s + (v - s) * decay_m        # v measured from rest; v_inf = s
        s *= decay_s
        peak = max(peak, v)
    return p.psp_peak / peak


class Brain:
    def __init__(self, indptr, indices, weights, pops,
                 dt: float = 2.0,
                 noise_rate: float = 0.0, noise_weight: float = 0.0,
                 exc_gain: float = 1.0, inh_gain: float = 1.5,
                 noise_pop: str | None = "central",
                 lamina_bias: float = 0.0,
                 seed: int | None = None):
        self.p = Params()
        self.dt = float(dt)
        self.n = len(indptr) - 1
        self.indptr = np.ascontiguousarray(indptr, dtype=np.int64)
        self.indices = np.ascontiguousarray(indices, dtype=np.int32)
        self.pops = pops
        self.rng = np.random.default_rng(seed)

        w_unit = _psp_calibration(self.dt, self.p)
        w = np.array(weights, dtype=np.float32) * w_unit
        w[w > 0] *= exc_gain
        w[w < 0] *= inh_gain
        self.weights = np.ascontiguousarray(w)

        self.v = np.full(self.n, self.p.v_rest, dtype=np.float32)
        self.vth = np.full(self.n, self.p.v_thresh, dtype=np.float32)
        self.s = np.zeros(self.n, dtype=np.float32)   # synaptic drive (mV)
        self.a = np.zeros(self.n, dtype=np.float32)   # adaptation (mV)
        d_s, d_m, d_a = _decays(self.dt, self.p)
        self.decay_s = np.float32(d_s)
        self.decay_m = np.float32(d_m)
        self.decay_a = np.float32(d_a)
        self.refract = np.zeros(self.n, dtype=np.int32)
        self.refract_steps = max(1, int(round(self.p.t_refract / self.dt)))

        # synaptic delay ring buffer
        self.delay_steps = max(1, int(round(self.p.delay / self.dt)))
        self.ring = np.zeros((self.delay_steps, self.n), dtype=np.float32)
        self.ring_pos = 0

        # background noise (spontaneity): Poisson synaptic bombardment,
        # regulated by a slow homeostat toward target_rate. Call it what
        # it is: a stability governor on an invented noise floor, not
        # "arousal". It raises the floor when the network goes quiet and
        # backs off when it rages, which is what keeps the network out of
        # the coma/seizure pair it otherwise collapses into. Real arousal
        # is neuromodulatory and largely octopaminergic, and this is not
        # that — octopamine multiplies drive that already exists, so it
        # could never do this job: multiplying a silent network keeps it
        # silent. All actual computation still runs through real synapses.
        # Noise goes only to the central brain by default: the optic lobes
        # (~100k of the 139k neurons) are driven by actual visual input, and
        # noise there makes the fly hallucinate looming objects.
        self.noise_rate = float(noise_rate)          # Hz per neuron (current)
        self.noise_base = float(noise_rate)
        self.noise_weight = np.float32(noise_weight * w_unit)  # in synapses
        if noise_pop and noise_pop in pops and len(pops[noise_pop]):
            self.noise_targets = np.asarray(pops[noise_pop], dtype=np.int64)
        else:
            self.noise_targets = np.arange(self.n, dtype=np.int64)
        self.target_rate = 1.0                       # Hz/neuron network mean
        self._rate_ema = 0.0                         # smoothed Hz/neuron

        # external drive: map neuron index -> forced firing rate (Hz)
        self._stim_idx = np.empty(0, dtype=np.int32)
        self._stim_p = np.empty(0, dtype=np.float32)

        # The giant fiber is one of the largest neurons in the fly and is
        # known for its high firing threshold — escape only triggers on
        # strong, synchronized looming drive. The paper's uniform threshold
        # makes it chronically excitable in a spontaneously active network,
        # so we give it (only it) a higher one.
        self.shift_threshold("GF", +10.0)

        # Lamina monopolar cells are graded, non-spiking neurons held at a
        # depolarized operating point; photoreceptor histamine inhibition
        # is released by darkness (the OFF response). A tonic bias current
        # emulates that operating point in the LIF approximation.
        self.bias = np.zeros(self.n, dtype=np.float32)
        if "lamina" in pops and len(pops["lamina"]):
            self.bias[pops["lamina"]] = np.float32(lamina_bias)

        self.t = 0.0            # simulated ms
        self.total_spikes = 0

    def shift_threshold(self, pop: str, delta_mv: float) -> None:
        if pop in self.pops and len(self.pops[pop]):
            self.vth[self.pops[pop]] += delta_mv

    def reset_state(self) -> None:
        """Fresh dynamical state (same anatomy): a new fly's brain."""
        self.v[:] = self.p.v_rest
        self.s[:] = 0.0
        self.a[:] = 0.0
        self.refract[:] = 0
        self.ring[:] = 0.0
        self.noise_rate = self.noise_base
        self._rate_ema = 0.0
        self._stim_idx = np.empty(0, dtype=np.int32)
        self._stim_p = np.empty(0, dtype=np.float32)

    # ---------------------------------------------------------------- stim
    def set_stimulus(self, stim: dict[str, float] | list):
        """Set forced firing rates for sensory neurons.

        Accepts {population_name: rate_hz} or [(indices_or_name, rates), ...]
        where rates is a scalar Hz or a per-neuron array of Hz (same length
        as the index array — this is how the retina drives each
        photoreceptor at its own rate). Stimulated neurons fire as Poisson
        processes, like the optogenetic-style activation in Shiu et al.
        """
        items = (stim.items() if isinstance(stim, dict) else stim)
        idx_parts, p_parts = [], []
        for key, rate in items:
            idx = self.pops[key] if isinstance(key, str) else key
            if len(idx) == 0:
                continue
            if isinstance(rate, np.ndarray):
                keep = rate > 0.0
                if not keep.any():
                    continue
                idx_parts.append(np.asarray(idx, dtype=np.int32)[keep])
                p_parts.append((rate[keep] * self.dt * 1e-3)
                               .astype(np.float32))
                continue
            if rate <= 0.0:
                continue
            idx_parts.append(np.asarray(idx, dtype=np.int32))
            p_parts.append(np.full(len(idx), rate * self.dt * 1e-3,
                                   dtype=np.float32))
        if idx_parts:
            self._stim_idx = np.concatenate(idx_parts)
            self._stim_p = np.concatenate(p_parts)
        else:
            self._stim_idx = np.empty(0, dtype=np.int32)
            self._stim_p = np.empty(0, dtype=np.float32)

    # ---------------------------------------------------------------- step
    def step(self) -> np.ndarray:
        """Advance one dt. Returns indices of neurons that spiked."""
        p, dt = self.p, self.dt

        # deliver delayed synaptic input, decay drive
        self.s *= self.decay_s
        self.s += self.ring[self.ring_pos]
        self.ring[self.ring_pos] = 0.0

        # background noise: sample the total Poisson event count, then
        # scatter events onto random neurons (much cheaper than per-neuron)
        if self.noise_rate > 0.0 and self.noise_weight > 0.0:
            m = len(self.noise_targets)
            lam = m * self.noise_rate * dt * 1e-3
            k = self.rng.poisson(lam)
            if k:
                hits = self.noise_targets[self.rng.integers(0, m, size=k)]
                np.add.at(self.s, hits, self.noise_weight)

        # membrane integration with spike-frequency adaptation.
        # Integrate everyone unconditionally (fast fused array ops), then
        # clamp the (few) refractory neurons back to reset.
        # exponential Euler: exact for input held constant over the step,
        # and unconditionally stable, unlike the forward Euler it replaces
        self.a *= self.decay_a
        v_inf = p.v_rest + self.s - self.a + self.bias
        self.v = v_inf + (self.v - v_inf) * self.decay_m
        ref = np.flatnonzero(self.refract > 0)
        if len(ref):
            self.v[ref] = p.v_reset
            self.refract[ref] -= 1

        # threshold crossing
        spiked = np.flatnonzero(self.v >= self.vth)

        # forced sensory spikes (Poisson at the commanded rate)
        if len(self._stim_idx):
            fire = self.rng.random(len(self._stim_idx),
                                   dtype=np.float32) < self._stim_p
            forced = self._stim_idx[fire]
            forced = forced[self.refract[forced] <= 0]
            if len(forced):
                spiked = np.union1d(spiked, forced)

        if len(spiked):
            self.v[spiked] = p.v_reset
            self.refract[spiked] = self.refract_steps
            self.a[spiked] += p.adapt_b
            self._propagate(spiked)
            self.total_spikes += len(spiked)

        # noise-floor governor: nudge the floor toward the target rate
        inst = len(spiked) * 1000.0 / (self.n * dt)      # Hz/neuron this step
        self._rate_ema += (inst - self._rate_ema) * (dt / 500.0)
        if self.noise_base > 0.0:
            err = self.target_rate - self._rate_ema
            self.noise_rate += err * (dt / 200.0) * self.noise_base * 0.1
            self.noise_rate = min(max(self.noise_rate, 0.0),
                                  self.noise_base * 3.0)

        self.ring_pos = (self.ring_pos + 1) % self.delay_steps
        self.t += dt
        return spiked

    def _propagate(self, spiked: np.ndarray) -> None:
        """Add outgoing weights of spiking neurons into the delay buffer."""
        starts = self.indptr[spiked]
        counts = (self.indptr[spiked + 1] - starts).astype(np.int64)
        total = int(counts.sum())
        if total == 0:
            return
        # flat positions of all outgoing synapses of all spiking neurons
        offsets = np.repeat(starts - np.concatenate(
            ([0], np.cumsum(counts)[:-1])), counts)
        flat = offsets + np.arange(total, dtype=np.int64)
        targets = self.indices[flat]
        contrib = np.bincount(targets, weights=self.weights[flat],
                              minlength=self.n).astype(np.float32)
        slot = (self.ring_pos + self.delay_steps - 1) % self.delay_steps
        self.ring[slot] += contrib

    # ------------------------------------------------------------- helpers
    def pop_count(self, spiked: np.ndarray, name: str) -> int:
        """How many spikes in `spiked` belong to population `name`."""
        return int(np.isin(spiked, self.pops[name], assume_unique=False).sum())


class RateMonitor:
    """Exponential moving average firing rate (Hz/neuron) per population."""

    def __init__(self, brain: Brain, names: list[str], tau_ms: float = 100.0):
        self.brain = brain
        self.names = [n for n in names if len(brain.pops.get(n, [])) > 0]
        self.sizes = {n: len(brain.pops[n]) for n in self.names}
        self.masks = {}
        for n in self.names:
            m = np.zeros(brain.n, dtype=bool)
            m[brain.pops[n]] = True
            self.masks[n] = m
        self.rates = dict.fromkeys(self.names, 0.0)
        self.decay = np.exp(-brain.dt / tau_ms)
        self.gain = (1.0 - self.decay) * 1000.0 / brain.dt  # -> Hz

    def update(self, spiked: np.ndarray) -> None:
        for n in self.names:
            k = int(self.masks[n][spiked].sum()) if len(spiked) else 0
            self.rates[n] = (self.rates[n] * self.decay
                             + self.gain * k / self.sizes[n])
