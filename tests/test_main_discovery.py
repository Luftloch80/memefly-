"""Integration-style test for the discovery orchestration in main.py.
Uses a fake signal engine (deterministic on price) so this tests the
wiring -- candidate ranking, held-mint gating, state persistence -- not
the neural math itself (covered by test_signal_engine.py).
"""
import time

import numpy as np
import pytest

from memefly import state_store
from memefly.config import load_config
from memefly.connectome import CircuitGraph
from memefly.discovery import CandidateRegistry
from memefly.main import run_once_discovery
from memefly.risk_manager import RiskConfig, RiskManager
from memefly.signal_engine import Action, TradeSignal
from memefly.trader import DryRunExecutor


class FakeEngine:
    """BUY with score == price above 0.002, otherwise HOLD."""

    def compute_signal(self, features):
        price = features.latest.price_usd
        if price > 0.002:
            return TradeSignal(Action.BUY, score=price, confidence=1.0, approach_spikes=1.0, avoidance_spikes=0.0)
        return TradeSignal(Action.HOLD, score=0.0, confidence=0.0, approach_spikes=0.0, avoidance_spikes=0.0)


class FakeFeed:
    def __init__(self, registry):
        self.registry = registry


def _tiny_graph() -> CircuitGraph:
    return CircuitGraph(body_ids=[1, 2], input_indices=[0], output_indices=[1], weights=np.zeros((2, 2)))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # run_once_discovery filters candidates using real time.time() internally,
    # so registry timestamps need to sit within the default [300s, 3600s]
    # age window relative to *now*, not an arbitrary small fake clock.
    created_at = time.time() - 400
    registry = CandidateRegistry()
    registry.register_new_token("mintA", "LOW", price_sol=0.001, now=created_at)
    registry.register_new_token("mintB", "HIGH", price_sol=0.005, now=created_at)
    registry.register_new_token("mintC", "MID", price_sol=0.003, now=created_at)
    for mint in ("mintA", "mintB", "mintC"):
        for _ in range(25):
            registry.record_trade(mint, price_sol=registry.get(mint).price_sol, now=created_at + 1)

    return {
        "cfg": load_config(),
        "engine": FakeEngine(),
        "risk_manager": RiskManager(RiskConfig(cooldown_seconds=0, max_trade_sol=1.0, max_position_sol=1.0)),
        "executor": DryRunExecutor(),
        "graph": _tiny_graph(),
        "feed": FakeFeed(registry),
        "histories": {},
    }


def _tick(env, now_offset=0.0):
    run_once_discovery(
        env["cfg"],
        env["engine"],
        env["risk_manager"],
        env["executor"],
        env["graph"],
        is_live=False,
        wallet_pubkey=None,
        feed=env["feed"],
        histories=env["histories"],
    )


def test_first_tick_only_warms_up_history_no_trade(env):
    _tick(env)
    assert env["risk_manager"].state.held_mint is None
    state = state_store.read_state()
    assert state["signal"]["action"] == "hold"


def test_second_tick_buys_the_highest_scoring_candidate(env):
    _tick(env)
    _tick(env)
    assert env["risk_manager"].state.held_mint == "mintB"
    trades = state_store.read_trades()
    assert trades[0]["action"] == "buy"
    assert trades[0]["mint"] == "mintB"


def test_cannot_buy_second_mint_while_holding_one(env):
    _tick(env)
    _tick(env)
    assert env["risk_manager"].state.held_mint == "mintB"

    # A third tick should evaluate the held mint's own exit signal, not
    # scan for new candidates to buy.
    _tick(env)
    trades = state_store.read_trades()
    assert all(t["mint"] == "mintB" for t in trades)


def test_state_lists_evaluated_candidates(env):
    _tick(env)
    _tick(env)
    state = state_store.read_state()
    by_mint = {c["mint"]: c["action"] for c in state["candidates"]}
    assert by_mint == {"mintA": "hold", "mintB": "buy", "mintC": "buy"}
