import numpy as np

from memefly.config import SignalConfig
from memefly.connectome import CircuitGraph
from memefly.market_data import MarketFeatures, MarketSnapshot
from memefly.signal_engine import Action, SignalEngine


def _graph() -> CircuitGraph:
    weights = np.zeros((6, 6))
    return CircuitGraph(body_ids=[10, 11, 12, 13, 14, 15], input_indices=[0, 1], output_indices=[2, 3, 4, 5], weights=weights)


class FakeSimulator:
    """Lets tests dictate exactly what spike counts come back."""

    def __init__(self, spike_counts: np.ndarray) -> None:
        self._spike_counts = spike_counts

    def run(self, input_currents, steps=25):
        return self._spike_counts


def _features() -> MarketFeatures:
    snap = MarketSnapshot(price_usd=1.0, volume_24h_usd=100.0, timestamp=0.0)
    return MarketFeatures(price_change_pct=0.1, volume_change_pct=0.1, volatility=0.1, latest=snap)


def test_all_approach_spikes_yields_buy():
    graph = _graph()
    # outputs = indices [2,3,4,5] -> approach half = first 2, avoidance = last 2
    spikes = np.array([0, 0, 10, 10, 0, 0])
    engine = SignalEngine(graph, SignalConfig(buy_threshold=0.2, sell_threshold=-0.2), simulator=FakeSimulator(spikes))
    signal = engine.compute_signal(_features())
    assert signal.action == Action.BUY
    assert signal.score > 0


def test_all_avoidance_spikes_yields_sell():
    graph = _graph()
    spikes = np.array([0, 0, 0, 0, 10, 10])
    engine = SignalEngine(graph, SignalConfig(buy_threshold=0.2, sell_threshold=-0.2), simulator=FakeSimulator(spikes))
    signal = engine.compute_signal(_features())
    assert signal.action == Action.SELL
    assert signal.score < 0


def test_balanced_spikes_yields_hold():
    graph = _graph()
    spikes = np.array([0, 0, 5, 5, 5, 5])
    engine = SignalEngine(graph, SignalConfig(buy_threshold=0.2, sell_threshold=-0.2), simulator=FakeSimulator(spikes))
    signal = engine.compute_signal(_features())
    assert signal.action == Action.HOLD


def test_no_spikes_yields_hold_and_zero_confidence():
    graph = _graph()
    spikes = np.zeros(6)
    engine = SignalEngine(graph, SignalConfig(), simulator=FakeSimulator(spikes))
    signal = engine.compute_signal(_features())
    assert signal.action == Action.HOLD
    assert signal.confidence == 0.0
