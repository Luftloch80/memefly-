from memefly import state_store


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state_store.write_state({"a": 1, "b": [1, 2, 3]}, path=path)
    assert state_store.read_state(path=path) == {"a": 1, "b": [1, 2, 3]}


def test_read_state_missing_file_returns_none(tmp_path):
    assert state_store.read_state(path=tmp_path / "missing.json") is None


def test_activity_log_round_trip(tmp_path):
    path = tmp_path / "activity_log.csv"
    row = state_store.ActivityRow(
        timestamp=1.0,
        price_usd=2.5,
        action="buy",
        score=0.4,
        confidence=0.8,
        approach_spikes=10.0,
        avoidance_spikes=2.0,
        reason="signal_buy",
        position_sol=0.05,
        daily_pnl_sol=0.0,
        halted=False,
    )
    state_store.record_activity(row, path=path)
    rows = state_store.read_activity(limit=10, path=path)
    assert len(rows) == 1
    assert rows[0]["action"] == "buy"
    assert rows[0]["price_usd"] == "2.5"


def test_activity_log_respects_limit(tmp_path):
    path = tmp_path / "activity_log.csv"
    for i in range(5):
        state_store.record_activity(
            state_store.ActivityRow(
                timestamp=float(i),
                price_usd=1.0,
                action="hold",
                score=0.0,
                confidence=0.0,
                approach_spikes=0.0,
                avoidance_spikes=0.0,
                reason="signal_hold",
                position_sol=0.0,
                daily_pnl_sol=0.0,
                halted=False,
            ),
            path=path,
        )
    rows = state_store.read_activity(limit=2, path=path)
    assert len(rows) == 2
    assert rows[-1]["timestamp"] == "4.0"


def test_trade_log_round_trip(tmp_path):
    path = tmp_path / "trade_log.csv"
    state_store.append_trade("buy", 0.05, 1.23, "signal_buy", "sig123", path=path)
    state_store.append_trade("sell", 0.05, 1.30, "take_profit_triggered", None, path=path)
    rows = state_store.read_trades(limit=10, path=path)
    # read_trades returns newest first
    assert rows[0]["action"] == "sell"
    assert rows[0]["signature"] == ""
    assert rows[1]["signature"] == "sig123"
