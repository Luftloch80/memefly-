"""Enforces hard position/loss limits regardless of what the signal engine
says. This is the last line of defense between a noisy neural signal and
real money moving.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from memefly.config import RiskConfig
from memefly.signal_engine import Action, TradeSignal


@dataclass(frozen=True)
class PlannedTrade:
    action: Action
    size_sol: float
    reason: str
    mint: str | None = None


@dataclass
class _State:
    position_sol: float = 0.0
    entry_price_usd: float | None = None
    held_mint: str | None = None
    daily_pnl_sol: float = 0.0
    day_start_ts: float = field(default_factory=time.time)
    last_trade_ts: float = 0.0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    """`mint` is optional everywhere: pass it in discovery mode (multiple
    candidate coins competing for the one allowed open position) to get
    single-position-at-a-time gating. Leave it out for the classic
    fixed-TARGET_TOKEN_MINT mode, where there's only ever one coin and the
    gating would be a no-op anyway.
    """

    def __init__(self, config: RiskConfig, now_fn=time.time) -> None:
        self.config = config
        self._now = now_fn
        self.state = _State(day_start_ts=now_fn())

    def _maybe_reset_day(self) -> None:
        now = self._now()
        if now - self.state.day_start_ts >= 86400:
            self.state.day_start_ts = now
            self.state.daily_pnl_sol = 0.0
            if self.state.halted and self.state.halt_reason == "daily_loss_limit":
                self.state.halted = False
                self.state.halt_reason = ""

    def decide(self, signal: TradeSignal, current_price_usd: float, mint: str | None = None) -> PlannedTrade:
        self._maybe_reset_day()
        s = self.state

        if s.halted:
            return PlannedTrade(Action.HOLD, 0.0, f"halted: {s.halt_reason}", mint=mint)

        holding_other_mint = mint is not None and s.position_sol > 0 and s.held_mint is not None and mint != s.held_mint
        if holding_other_mint:
            return PlannedTrade(Action.HOLD, 0.0, "position_open_in_other_mint", mint=mint)

        # Stop-loss / take-profit on an existing position overrides the signal.
        if s.position_sol > 0 and s.entry_price_usd:
            change = (current_price_usd - s.entry_price_usd) / s.entry_price_usd
            if change <= -self.config.stop_loss_pct:
                return PlannedTrade(Action.SELL, s.position_sol, "stop_loss_triggered", mint=s.held_mint or mint)
            if change >= self.config.take_profit_pct:
                return PlannedTrade(Action.SELL, s.position_sol, "take_profit_triggered", mint=s.held_mint or mint)

        if self._now() - s.last_trade_ts < self.config.cooldown_seconds:
            return PlannedTrade(Action.HOLD, 0.0, "cooldown_active", mint=mint)

        if signal.action == Action.HOLD:
            return PlannedTrade(Action.HOLD, 0.0, "signal_hold", mint=mint)

        if signal.action == Action.BUY:
            room = self.config.max_position_sol - s.position_sol
            if room <= 0:
                return PlannedTrade(Action.HOLD, 0.0, "max_position_reached", mint=mint)
            size = min(self.config.max_trade_sol, room) * signal.confidence
            if size <= 0:
                return PlannedTrade(Action.HOLD, 0.0, "zero_confidence", mint=mint)
            return PlannedTrade(Action.BUY, size, "signal_buy", mint=mint)

        if signal.action == Action.SELL:
            if s.position_sol <= 0:
                return PlannedTrade(Action.HOLD, 0.0, "no_position_to_sell", mint=mint)
            size = min(self.config.max_trade_sol, s.position_sol) * signal.confidence
            if size <= 0:
                return PlannedTrade(Action.HOLD, 0.0, "zero_confidence", mint=mint)
            return PlannedTrade(Action.SELL, size, "signal_sell", mint=s.held_mint or mint)

        return PlannedTrade(Action.HOLD, 0.0, "unhandled", mint=mint)

    def record_fill(
        self,
        action: Action,
        size_sol: float,
        price_usd: float,
        realized_pnl_sol: float = 0.0,
        mint: str | None = None,
    ) -> None:
        s = self.state
        s.last_trade_ts = self._now()
        s.daily_pnl_sol += realized_pnl_sol

        if action == Action.BUY:
            if s.position_sol > 0 and s.entry_price_usd:
                total = s.position_sol + size_sol
                s.entry_price_usd = (s.entry_price_usd * s.position_sol + price_usd * size_sol) / total
            else:
                s.entry_price_usd = price_usd
            s.position_sol += size_sol
            if mint is not None:
                s.held_mint = mint
        elif action == Action.SELL:
            s.position_sol = max(0.0, s.position_sol - size_sol)
            if s.position_sol == 0:
                s.entry_price_usd = None
                s.held_mint = None

        if s.daily_pnl_sol <= -self.config.max_daily_loss_sol:
            s.halted = True
            s.halt_reason = "daily_loss_limit"
