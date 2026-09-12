"""Autonomous coin discovery via PumpPortal's live WebSocket feed.

Splits cleanly into two parts:
  - CandidateRegistry: pure, thread-safe bookkeeping of "what tokens have
    we seen, how old are they, how much trade activity do they have" --
    fully unit-testable with an injected clock, no network involved.
  - PumpPortalTokenFeed: the actual WebSocket connection that feeds the
    registry. This talks to a third-party, community-documented API
    (https://pumpportal.fun/data-api/real-time) that can change without
    notice -- verify the message shapes below still match before relying
    on this in production.

Most brand-new pump.fun tokens are rugs that go to zero within minutes.
The age/min-trade filters here cut down on the very newest, highest-risk
tokens, but they do not make this safe -- they make it less reckless.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field

from memefly.config import DiscoveryConfig

logger = logging.getLogger(__name__)


@dataclass
class TokenCandidate:
    mint: str
    symbol: str
    created_at: float
    price_sol: float
    trade_count: int
    last_update: float


class CandidateRegistry:
    """Thread-safe registry of recently discovered tokens. All methods take
    an explicit `now` so this class has no hidden dependency on the wall
    clock and is trivial to unit test.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._candidates: dict[str, TokenCandidate] = {}

    def register_new_token(self, mint: str, symbol: str, price_sol: float, now: float) -> None:
        with self._lock:
            if mint in self._candidates:
                return
            self._candidates[mint] = TokenCandidate(
                mint=mint, symbol=symbol, created_at=now, price_sol=price_sol, trade_count=0, last_update=now
            )

    def record_trade(self, mint: str, price_sol: float, now: float) -> None:
        with self._lock:
            candidate = self._candidates.get(mint)
            if candidate is None:
                return
            candidate.price_sol = price_sol
            candidate.trade_count += 1
            candidate.last_update = now

    def prune(self, now: float, max_age_seconds: int, max_candidates: int, protect: frozenset[str] = frozenset()) -> None:
        """`protect` exempts a mint (typically the currently held position)
        from both age- and capacity-based eviction, since we still need
        live price updates for it long after it would otherwise age out.
        """
        with self._lock:
            for mint in [
                m for m, c in self._candidates.items() if m not in protect and now - c.created_at > max_age_seconds
            ]:
                del self._candidates[mint]

            over_capacity = len(self._candidates) - max_candidates
            if over_capacity > 0:
                evictable = [c for c in self._candidates.values() if c.mint not in protect]
                ranked = sorted(evictable, key=lambda c: (c.trade_count, c.last_update))
                for c in ranked[:over_capacity]:
                    del self._candidates[c.mint]

    def get_candidates(self, now: float, min_age_seconds: int, max_age_seconds: int, min_trades: int) -> list[TokenCandidate]:
        with self._lock:
            values = list(self._candidates.values())
        return [
            c
            for c in values
            if min_age_seconds <= (now - c.created_at) <= max_age_seconds and c.trade_count >= min_trades
        ]

    def get(self, mint: str) -> TokenCandidate | None:
        """Unfiltered single lookup -- used to keep tracking price for the
        currently held mint even once it falls outside the entry filters.
        """
        with self._lock:
            candidate = self._candidates.get(mint)
            return TokenCandidate(**vars(candidate)) if candidate else None

    def size(self) -> int:
        with self._lock:
            return len(self._candidates)

    def all_mints(self) -> list[str]:
        with self._lock:
            return list(self._candidates.keys())


def _bonding_curve_price_sol(msg: dict) -> float | None:
    v_sol = msg.get("vSolInBondingCurve")
    v_tokens = msg.get("vTokensInBondingCurve")
    if v_sol is None or v_tokens in (None, 0):
        return None
    try:
        return float(v_sol) / float(v_tokens)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class PumpPortalTokenFeed:
    """Runs a background thread holding a WebSocket connection to
    PumpPortal, subscribing to new-token creation and trade events for
    every token it discovers, and feeding a CandidateRegistry.
    """

    def __init__(
        self,
        config: DiscoveryConfig,
        registry: CandidateRegistry | None = None,
        protected_mint_getter=lambda: None,
    ) -> None:
        self.config = config
        self.registry = registry or CandidateRegistry()
        # Lets the caller (main.py) tell us which mint is the currently
        # held position, so our own pruning never evicts it out from under
        # an open trade -- e.g. `lambda: risk_manager.state.held_mint`.
        self.protected_mint_getter = protected_mint_getter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscribed_trades: set[str] = set()
        self._messages_seen = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._run_once()
                backoff = 1.0
            except Exception as exc:  # noqa: BLE001
                logger.warning("PumpPortal feed disconnected (%s), reconnecting in %.0fs", exc, backoff)
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60.0)

    def _run_once(self) -> None:
        # Imported lazily so the rest of the package doesn't need
        # websocket-client installed unless discovery mode is actually on.
        import websocket

        ws = websocket.create_connection(self.config.ws_url, timeout=30)
        logger.info("PumpPortal feed connected (%s)", self.config.ws_url)
        try:
            ws.send(json.dumps({"method": "subscribeNewToken"}))
            self._subscribed_trades.clear()

            # After a reconnect, re-subscribe to trade updates for anything
            # we already knew about (in particular, a currently held
            # position) so it doesn't silently stop getting price updates.
            protected_mint = self.protected_mint_getter()
            resubscribe = set(self.registry.all_mints())
            if protected_mint:
                resubscribe.add(protected_mint)
            if resubscribe:
                ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": list(resubscribe)}))
                self._subscribed_trades.update(resubscribe)

            while not self._stop.is_set():
                raw = ws.recv()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                self._messages_seen += 1
                if self._messages_seen <= 5:
                    # Prints the raw shape of the first few messages so you
                    # can confirm real traffic is flowing and see whether
                    # PumpPortal's message format still matches what
                    # _handle_message expects (txType/mint/vSolInBondingCurve/
                    # vTokensInBondingCurve).
                    logger.info("PumpPortal message #%d: %s", self._messages_seen, msg)
                elif self._messages_seen % 200 == 0:
                    logger.info(
                        "PumpPortal feed: %d messages received so far, %d tokens in registry",
                        self._messages_seen,
                        self.registry.size(),
                    )

                self._handle_message(msg, ws)
                protected_mint = self.protected_mint_getter()
                protect = frozenset({protected_mint}) if protected_mint else frozenset()
                self.registry.prune(time.time(), self.config.max_age_seconds, self.config.max_candidates, protect=protect)
        finally:
            ws.close()

    def _handle_message(self, msg: dict, ws) -> None:
        mint = msg.get("mint")
        if not mint:
            return
        tx_type = msg.get("txType")
        price = _bonding_curve_price_sol(msg) or 0.0
        now = time.time()

        if tx_type == "create":
            self.registry.register_new_token(mint, msg.get("symbol", "?"), price, now)
            if mint not in self._subscribed_trades:
                ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
                self._subscribed_trades.add(mint)
        elif tx_type in ("buy", "sell"):
            self.registry.record_trade(mint, price, now)
