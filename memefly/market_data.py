"""Fetches price/volume for the target token and derives simple features
(percent change, volatility) from a rolling history.

Uses Dexscreener's public API (no key required) since it covers pump.fun
pairs once they have on-chain liquidity. Very new pre-graduation pump.fun
tokens may not show up yet -- check the mint on https://dexscreener.com first.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Protocol

import requests

logger = logging.getLogger(__name__)

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


@dataclass(frozen=True)
class MarketSnapshot:
    price_usd: float
    volume_24h_usd: float
    timestamp: float


class MarketDataProvider(Protocol):
    def fetch(self, token_mint: str) -> MarketSnapshot: ...


class DexscreenerProvider:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, token_mint: str) -> MarketSnapshot:
        resp = requests.get(DEXSCREENER_URL.format(mint=token_mint), timeout=self.timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        pairs = data.get("pairs") or []
        if not pairs:
            raise ValueError(f"No Dexscreener pairs found for mint {token_mint}")
        # Use the pair with the highest liquidity as the primary quote.
        best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0.0))
        price = float(best.get("priceUsd") or 0.0)
        volume = float((best.get("volume") or {}).get("h24") or 0.0)
        return MarketSnapshot(price_usd=price, volume_24h_usd=volume, timestamp=time.time())


@dataclass
class MarketFeatures:
    price_change_pct: float
    volume_change_pct: float
    volatility: float
    latest: MarketSnapshot


class MarketHistory:
    """Rolling window of snapshots used to derive normalized features."""

    def __init__(self, max_len: int = 30) -> None:
        self._buf: Deque[MarketSnapshot] = deque(maxlen=max_len)

    def push(self, snapshot: MarketSnapshot) -> MarketFeatures:
        self._buf.append(snapshot)
        prices = [s.price_usd for s in self._buf]
        volumes = [s.volume_24h_usd for s in self._buf]

        price_change_pct = _pct_change(prices)
        volume_change_pct = _pct_change(volumes)
        volatility = _stddev(prices) / prices[-1] if prices[-1] else 0.0

        return MarketFeatures(
            price_change_pct=price_change_pct,
            volume_change_pct=volume_change_pct,
            volatility=volatility,
            latest=snapshot,
        )

    def __len__(self) -> int:
        return len(self._buf)


def _pct_change(series: list[float]) -> float:
    if len(series) < 2 or series[0] == 0:
        return 0.0
    return (series[-1] - series[0]) / series[0]


def _stddev(series: list[float]) -> float:
    if len(series) < 2:
        return 0.0
    mean = sum(series) / len(series)
    variance = sum((x - mean) ** 2 for x in series) / len(series)
    return variance**0.5
