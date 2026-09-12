from memefly.config import RiskConfig
from memefly.risk_manager import RiskManager
from memefly.signal_engine import Action, TradeSignal


def _signal(action: Action, score: float = 0.5, confidence: float = 1.0) -> TradeSignal:
    return TradeSignal(action=action, score=score, confidence=confidence, approach_spikes=1.0, avoidance_spikes=0.0)


def test_buy_within_limits_is_sized_by_confidence():
    cfg = RiskConfig(max_trade_sol=0.1, max_position_sol=1.0, cooldown_seconds=0)
    rm = RiskManager(cfg)
    planned = rm.decide(_signal(Action.BUY, confidence=0.5), current_price_usd=1.0)
    assert planned.action == Action.BUY
    assert planned.size_sol == 0.05


def test_cooldown_blocks_rapid_retrade():
    cfg = RiskConfig(max_trade_sol=0.1, max_position_sol=1.0, cooldown_seconds=300)
    rm = RiskManager(cfg)
    first = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    rm.record_fill(first.action, first.size_sol, price_usd=1.0)
    second = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    assert second.action == Action.HOLD
    assert second.reason == "cooldown_active"


def test_cannot_exceed_max_position():
    cfg = RiskConfig(max_trade_sol=1.0, max_position_sol=0.1, cooldown_seconds=0)
    rm = RiskManager(cfg)
    first = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    assert first.size_sol <= 0.1
    rm.record_fill(first.action, first.size_sol, price_usd=1.0)
    second = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    assert second.action == Action.HOLD
    assert second.reason == "max_position_reached"


def test_sell_without_position_is_noop():
    cfg = RiskConfig(cooldown_seconds=0)
    rm = RiskManager(cfg)
    planned = rm.decide(_signal(Action.SELL), current_price_usd=1.0)
    assert planned.action == Action.HOLD
    assert planned.reason == "no_position_to_sell"


def test_stop_loss_forces_sell():
    cfg = RiskConfig(max_trade_sol=1.0, max_position_sol=1.0, cooldown_seconds=0, stop_loss_pct=0.2)
    rm = RiskManager(cfg)
    buy = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    rm.record_fill(buy.action, buy.size_sol, price_usd=1.0)
    planned = rm.decide(_signal(Action.HOLD), current_price_usd=0.75)  # -25%
    assert planned.action == Action.SELL
    assert planned.reason == "stop_loss_triggered"


def test_daily_loss_limit_halts_trading():
    cfg = RiskConfig(max_trade_sol=1.0, max_position_sol=1.0, cooldown_seconds=0, max_daily_loss_sol=0.1)
    rm = RiskManager(cfg)
    buy = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    rm.record_fill(buy.action, buy.size_sol, price_usd=1.0, realized_pnl_sol=-0.2)
    planned = rm.decide(_signal(Action.BUY), current_price_usd=1.0)
    assert planned.action == Action.HOLD
    assert "halted" in planned.reason
