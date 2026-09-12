"""Turns market features into neural input, runs the LIF simulation over
the real connectome circuit, and turns the resulting spikes into a trade
signal.

Convention (arbitrary, not biologically validated): the circuit's output
neurons are split in half by body-ID order. The first half's spike count
is treated as "approach" (bullish) activity, the second half as
"avoidance" (bearish) activity. This is a stylized convention borrowed
from the fact that real mushroom-body output neurons are known to
segregate into approach- and avoidance-promoting populations -- but which
specific neurons fall on which side of the biological split is not what's
being modeled here.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

import numpy as np

from memefly.connectome import CircuitGraph, LIFSimulator
from memefly.config import SignalConfig
from memefly.market_data import MarketFeatures


class Action(enum.Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class TradeSignal:
    action: Action
    score: float  # in [-1, 1], positive = bullish
    confidence: float  # in [0, 1]
    approach_spikes: float
    avoidance_spikes: float
    # Per-neuron spike counts for the dashboard's neuron-activity view.
    approach_neuron_spikes: tuple[float, ...] = ()
    avoidance_neuron_spikes: tuple[float, ...] = ()


def features_to_input_currents(features: MarketFeatures, n_inputs: int, current_scale: float = 2.0) -> np.ndarray:
    """Deterministically distributes the three market features across the
    circuit's real input neurons.
    """
    raw = np.array(
        [
            np.clip(features.price_change_pct, -1.0, 1.0),
            np.clip(features.volume_change_pct, -1.0, 1.0),
            np.clip(features.volatility, 0.0, 1.0),
        ]
    )
    currents = np.zeros(n_inputs, dtype=np.float64)
    for i in range(n_inputs):
        currents[i] = raw[i % len(raw)] * current_scale
    return currents


def _split_output(graph: CircuitGraph) -> tuple[list[int], list[int]]:
    ordered = sorted(range(len(graph.output_indices)), key=lambda i: graph.body_ids[graph.output_indices[i]])
    half = len(ordered) // 2 or 1
    approach = [graph.output_indices[i] for i in ordered[:half]]
    avoidance = [graph.output_indices[i] for i in ordered[half:]] or approach
    return approach, avoidance


class SignalEngine:
    def __init__(self, graph: CircuitGraph, config: SignalConfig, simulator: LIFSimulator | None = None) -> None:
        self.graph = graph
        self.config = config
        self.simulator = simulator or LIFSimulator(graph)
        self.approach_indices, self.avoidance_indices = _split_output(graph)

    def compute_signal(self, features: MarketFeatures) -> TradeSignal:
        currents = features_to_input_currents(features, len(self.graph.input_indices))
        spike_counts = self.simulator.run(currents)

        approach_neuron_spikes = spike_counts[self.approach_indices]
        avoidance_neuron_spikes = spike_counts[self.avoidance_indices]
        approach = float(approach_neuron_spikes.sum())
        avoidance = float(avoidance_neuron_spikes.sum())
        total = approach + avoidance

        score = 0.0 if total == 0 else (approach - avoidance) / total
        confidence = min(1.0, total / (len(self.graph.output_indices) * 5.0 + 1e-9))

        if score >= self.config.buy_threshold:
            action = Action.BUY
        elif score <= self.config.sell_threshold:
            action = Action.SELL
        else:
            action = Action.HOLD

        return TradeSignal(
            action=action,
            score=score,
            confidence=confidence,
            approach_spikes=approach,
            avoidance_spikes=avoidance,
            approach_neuron_spikes=tuple(approach_neuron_spikes.tolist()),
            avoidance_neuron_spikes=tuple(avoidance_neuron_spikes.tolist()),
        )
