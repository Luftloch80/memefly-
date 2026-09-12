"""Real fly connectome circuit, fetched via neuPrint, driving a small
leaky-integrate-and-fire (LIF) simulation.

Biological grounding, and its limits
-------------------------------------
By default this pulls the antennal-lobe projection neurons (PNs) and the
mushroom-body output neurons (MBONs) from the hemibrain connectome
(https://neuprint.janelia.org) -- a real, published circuit that in the
actual fly carries olfactory sensory information to behavioral output
neurons. Here we repurpose it: "sensory input" is market data instead of
odor, and "behavioral output" is a buy/sell/hold signal instead of
approach/avoidance behavior.

This produces a real, deterministic-given-its-inputs neural simulation.
It does NOT give the fly brain any actual insight into token prices --
there is no evolutionary or causal link between fly olfaction and Solana
markets. Treat the output as a novelty signal generator, not a genuine
market predictor.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from memefly.config import NeuprintConfig

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/connectome")


@dataclass
class CircuitGraph:
    """A fixed subgraph of real neurons and real synapse weights."""

    body_ids: list[int]
    input_indices: list[int]
    output_indices: list[int]
    weights: np.ndarray  # weights[i, j] = synapse count from neuron i -> neuron j

    def to_cache_dict(self) -> dict:
        return {
            "body_ids": self.body_ids,
            "input_indices": self.input_indices,
            "output_indices": self.output_indices,
            "weights": self.weights.tolist(),
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "CircuitGraph":
        return cls(
            body_ids=data["body_ids"],
            input_indices=data["input_indices"],
            output_indices=data["output_indices"],
            weights=np.array(data["weights"], dtype=np.float64),
        )


class ConnectomeError(Exception):
    pass


def _cache_path(cfg: NeuprintConfig, cache_dir: Path) -> Path:
    safe_dataset = re.sub(r"[^A-Za-z0-9_.-]", "_", cfg.dataset)
    return cache_dir / f"{safe_dataset}.json"


def fetch_circuit(cfg: NeuprintConfig, cache_dir: Path = DEFAULT_CACHE_DIR, use_cache: bool = True) -> CircuitGraph:
    """Fetch (or load a cached copy of) a real input->output circuit.

    Requires the `neuprint-python` package and a valid NEUPRINT_TOKEN. The
    fetched graph is cached to disk so the (slow, rate-limited) neuPrint API
    is only hit once per dataset/config combination.
    """
    path = _cache_path(cfg, cache_dir)
    if use_cache and path.exists():
        logger.info("Loading cached connectome circuit from %s", path)
        with open(path, "r", encoding="utf-8") as fh:
            return CircuitGraph.from_cache_dict(json.load(fh))

    if not cfg.token:
        raise ConnectomeError(
            "NEUPRINT_TOKEN is not set and no cached circuit exists. "
            "Get a free token at https://neuprint.janelia.org and set it in .env, "
            "or provide a pre-built cache file."
        )

    try:
        from neuprint import Client, NeuronCriteria as NC, fetch_adjacencies
    except ImportError as exc:
        raise ConnectomeError(
            "neuprint-python is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    logger.info("Fetching circuit from neuPrint dataset=%s (this hits a real API)", cfg.dataset)
    client = Client(cfg.server, dataset=cfg.dataset, token=cfg.token)

    sources = NC(type=cfg.input_type_regex, regex=True, client=client)
    targets = NC(type=cfg.output_type_regex, regex=True, client=client)

    neuron_df, conn_df = fetch_adjacencies(sources, targets, client=client)

    if neuron_df.empty or conn_df.empty:
        raise ConnectomeError(
            f"neuPrint query returned no neurons/connections for dataset={cfg.dataset!r} "
            f"input_regex={cfg.input_type_regex!r} output_regex={cfg.output_type_regex!r}. "
            "Check your regexes against the dataset's neuron types."
        )

    body_ids = sorted(set(neuron_df["bodyId"].tolist()))
    if len(body_ids) > cfg.max_neurons:
        body_ids = body_ids[: cfg.max_neurons]
    id_to_idx = {bid: i for i, bid in enumerate(body_ids)}
    id_set = set(body_ids)

    input_type_re = re.compile(cfg.input_type_regex)
    output_type_re = re.compile(cfg.output_type_regex)
    type_by_id = dict(zip(neuron_df["bodyId"], neuron_df.get("type", [""] * len(neuron_df))))

    input_indices = sorted(
        {id_to_idx[bid] for bid in body_ids if input_type_re.match(str(type_by_id.get(bid, "")))}
    )
    output_indices = sorted(
        {id_to_idx[bid] for bid in body_ids if output_type_re.match(str(type_by_id.get(bid, "")))}
    )

    n = len(body_ids)
    weights = np.zeros((n, n), dtype=np.float64)
    for _, row in conn_df.iterrows():
        pre, post, w = row["bodyId_pre"], row["bodyId_post"], row["weight"]
        if pre in id_set and post in id_set:
            weights[id_to_idx[pre], id_to_idx[post]] += float(w)

    graph = CircuitGraph(
        body_ids=body_ids,
        input_indices=input_indices or list(range(min(10, n))),
        output_indices=output_indices or list(range(max(0, n - 10), n)),
        weights=weights,
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph.to_cache_dict(), fh)
    logger.info("Cached circuit (%d neurons, %d in, %d out) to %s", n, len(graph.input_indices), len(graph.output_indices), path)

    return graph


class LIFSimulator:
    """Minimal leaky-integrate-and-fire simulation over a fixed weight graph.

    This is a stylized, simplified spiking model -- real biophysical neuron
    dynamics involve far more (ion channels, dendritic morphology, neuromodulation,
    etc). It is only meant to turn a real synaptic weight matrix into a
    reproducible dynamical system that responds to external input.
    """

    def __init__(
        self,
        graph: CircuitGraph,
        decay: float = 0.85,
        threshold: float = 1.0,
        weight_scale: float | None = None,
        seed: int | None = None,
    ) -> None:
        self.graph = graph
        self.decay = decay
        self.threshold = threshold
        n = graph.weights.shape[0]
        max_w = graph.weights.max() if graph.weights.size else 0.0
        # Normalize real synapse-count weights into a numerically stable range.
        self.weight_scale = weight_scale if weight_scale is not None else (1.0 / max_w if max_w > 0 else 1.0)
        self._rng = np.random.default_rng(seed)
        self.n = n

    def run(self, input_currents: np.ndarray, steps: int = 25) -> np.ndarray:
        """Inject `input_currents` into the input neurons each step, propagate
        through the real weight matrix, and return spike counts per neuron
        over the run.
        """
        n = self.n
        potential = np.zeros(n, dtype=np.float64)
        spike_counts = np.zeros(n, dtype=np.float64)
        w = self.graph.weights * self.weight_scale

        for _ in range(steps):
            potential *= self.decay
            for idx, current in zip(self.graph.input_indices, input_currents):
                potential[idx] += current
            spiking = potential >= self.threshold
            spike_counts += spiking
            potential[spiking] = 0.0
            if spiking.any():
                potential += spiking.astype(np.float64) @ w

        return spike_counts

    def output_spike_counts(self, spike_counts: np.ndarray) -> np.ndarray:
        return spike_counts[self.graph.output_indices]
