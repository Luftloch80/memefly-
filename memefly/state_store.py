"""Shared persistence for the trading loop (memefly/main.py) and the
dashboard (memefly/dashboard.py), which run as separate processes.

Every iteration of the loop -- trade or not -- writes:
  - state.json: a single latest snapshot (wallet/position/last signal)
  - activity_log.csv: one row per iteration, for charting history
Trades additionally append to trade_log.csv (only rows where an order
was actually placed, dry-run included).

All files are gitignored; they're local runtime data, not source.
"""
from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATE_PATH = Path("state.json")
ACTIVITY_LOG_PATH = Path("activity_log.csv")
TRADE_LOG_PATH = Path("trade_log.csv")

ACTIVITY_FIELDS = [
    "timestamp",
    "mint",
    "price_usd",
    "action",
    "score",
    "confidence",
    "approach_spikes",
    "avoidance_spikes",
    "reason",
    "position_sol",
    "daily_pnl_sol",
    "halted",
]

TRADE_FIELDS = ["timestamp", "mint", "action", "size_sol", "price_usd", "reason", "signature"]


@dataclass
class ActivityRow:
    timestamp: float
    price_usd: float
    action: str
    score: float
    confidence: float
    approach_spikes: float
    avoidance_spikes: float
    reason: str
    position_sol: float
    daily_pnl_sol: float
    halted: bool
    mint: str = ""


def _append_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def record_activity(row: ActivityRow, path: Path = ACTIVITY_LOG_PATH) -> None:
    _append_csv_row(path, ACTIVITY_FIELDS, asdict(row))


def append_trade(
    action: str,
    size_sol: float,
    price_usd: float,
    reason: str,
    signature: str | None,
    path: Path = TRADE_LOG_PATH,
    mint: str = "",
) -> None:
    _append_csv_row(
        path,
        TRADE_FIELDS,
        {
            "timestamp": time.time(),
            "mint": mint,
            "action": action,
            "size_sol": size_sol,
            "price_usd": price_usd,
            "reason": reason,
            "signature": signature or "",
        },
    )


def write_state(data: dict[str, Any], path: Path = STATE_PATH) -> None:
    """Atomic write so the dashboard never reads a half-written file."""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp_path, path)


def read_state(path: Path = STATE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_csv_tail(path: Path, limit: int) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-limit:]


def read_activity(limit: int = 200, path: Path = ACTIVITY_LOG_PATH) -> list[dict[str, str]]:
    return _read_csv_tail(path, limit)


def read_trades(limit: int = 100, path: Path = TRADE_LOG_PATH) -> list[dict[str, str]]:
    return list(reversed(_read_csv_tail(path, limit)))
