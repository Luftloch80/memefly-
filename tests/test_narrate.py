from memefly.main import _narrate, _update_thought
from memefly.risk_manager import PlannedTrade
from memefly.signal_engine import Action, TradeSignal


def _signal(action=Action.HOLD, score=0.0, confidence=0.0):
    return TradeSignal(action=action, score=score, confidence=confidence, approach_spikes=0.0, avoidance_spikes=0.0)


def test_narrate_halted_takes_priority():
    text = _narrate("fixed", _signal(), PlannedTrade(Action.HOLD, 0.0, "signal_hold"), [], None, True, "daily_loss_limit", 0)
    assert "halted" in text.lower()
    assert "daily loss limit" in text


def test_narrate_fixed_mode_buy():
    text = _narrate("fixed", _signal(Action.BUY, 0.5, 0.8), PlannedTrade(Action.BUY, 0.05, "signal_buy"), [], None, False, "", 0)
    assert "0.05" in text
    assert "buy" in text.lower()


def test_narrate_fixed_mode_hold():
    text = _narrate("fixed", _signal(Action.HOLD, 0.05), PlannedTrade(Action.HOLD, 0.0, "cooldown_active"), [], None, False, "", 0)
    assert "cooldown active" in text


def test_narrate_discovery_holding_position():
    text = _narrate(
        "discovery", _signal(Action.HOLD, 0.1, 0.4), PlannedTrade(Action.HOLD, 0.0, "signal_hold"),
        [], "Mint1111111111111111111111111111111111111", False, "", 5,
    )
    assert "Mint" in text
    assert "Holding" in text


def test_narrate_discovery_no_candidates_yet():
    text = _narrate("discovery", _signal(), PlannedTrade(Action.HOLD, 0.0, "no_buy_candidate"), [], None, False, "", 12)
    assert "12 tracked" in text
    assert "Scanning" in text


def test_narrate_discovery_candidates_but_no_buy():
    candidates = [{"mint": "abc", "symbol": "FOO", "score": 0.15, "confidence": 0.3, "action": "hold"}]
    text = _narrate("discovery", _signal(), PlannedTrade(Action.HOLD, 0.0, "no_buy_candidate"), candidates, None, False, "", 3)
    assert "FOO" in text
    assert "1 coin" in text


def test_narrate_discovery_buys_new_candidate():
    text = _narrate(
        "discovery", _signal(Action.BUY, 0.6, 0.9),
        PlannedTrade(Action.BUY, 0.04, "signal_buy", mint="Mint2222222222222222222222222222222222222"),
        [], None, False, "", 4,
    )
    assert "Found something promising" in text


def test_update_thought_preserves_other_state_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from memefly import state_store

    state_store.write_state({"foo": "bar", "thought": "old"})
    _update_thought("new thought")
    state = state_store.read_state()
    assert state["foo"] == "bar"
    assert state["thought"] == "new thought"


def test_update_thought_works_with_no_prior_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from memefly import state_store

    _update_thought("first thought")
    assert state_store.read_state()["thought"] == "first thought"
