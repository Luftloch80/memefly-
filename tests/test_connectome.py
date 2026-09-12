import numpy as np

from memefly.connectome import CircuitGraph, LIFSimulator


def _tiny_graph() -> CircuitGraph:
    # 4 neurons: 0,1 are inputs; 2,3 are outputs. 0->2 and 1->3 are strongly
    # connected, 0->3 and 1->2 are not connected at all.
    weights = np.array(
        [
            [0, 0, 5, 0],
            [0, 0, 0, 5],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.float64,
    )
    return CircuitGraph(body_ids=[1, 2, 3, 4], input_indices=[0, 1], output_indices=[2, 3], weights=weights)


def test_lif_simulator_is_deterministic():
    graph = _tiny_graph()
    sim = LIFSimulator(graph, decay=0.5, threshold=1.0)
    a = sim.run(np.array([1.0, 0.0]), steps=10)
    b = sim.run(np.array([1.0, 0.0]), steps=10)
    assert np.array_equal(a, b)


def test_lif_simulator_routes_input_through_real_weights():
    graph = _tiny_graph()
    sim = LIFSimulator(graph, decay=0.9, threshold=1.0)
    # Only neuron 0 (-> output 2) gets driven; output 3 should stay silent.
    spikes = sim.run(np.array([2.0, 0.0]), steps=5)
    out = sim.output_spike_counts(spikes)
    assert out[0] > 0  # neuron 2 spiked
    assert out[1] == 0  # neuron 3 never received input or upstream spikes


def test_no_input_produces_no_spikes():
    graph = _tiny_graph()
    sim = LIFSimulator(graph, decay=0.9, threshold=1.0)
    spikes = sim.run(np.array([0.0, 0.0]), steps=20)
    assert spikes.sum() == 0
