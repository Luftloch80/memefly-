"""CLI entry point: python -m memefly.main [--live] [--once] [--interval N]

Safety: going live requires ALL THREE of:
  1. the --live CLI flag (explicit, per-invocation)
  2. LIVE_TRADING=true in the environment/.env
  3. I_UNDERSTAND_THE_RISK=yes in the environment/.env
Missing any one of these falls back to dry-run, no exceptions.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

from memefly.config import load_config
from memefly.connectome import ConnectomeError, fetch_circuit
from memefly.market_data import DexscreenerProvider, MarketHistory
from memefly.risk_manager import RiskManager
from memefly.signal_engine import Action, SignalEngine
from memefly.trader import DryRunExecutor, PumpPortalExecutor, TradeExecutor
from memefly.wallet import WalletError, load_keypair

logger = logging.getLogger("memefly")

TRADE_LOG_PATH = Path("trade_log.csv")


def _log_trade_row(action: Action, size_sol: float, price_usd: float, reason: str, signature: str | None) -> None:
    is_new = not TRADE_LOG_PATH.exists()
    with open(TRADE_LOG_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["timestamp", "action", "size_sol", "price_usd", "reason", "signature"])
        writer.writerow([time.time(), action.value, size_sol, price_usd, reason, signature or ""])


def build_executor(args: argparse.Namespace, cfg) -> TradeExecutor:
    if not args.live:
        logger.info("Running in DRY RUN mode (pass --live plus env safety switches for real trades).")
        return DryRunExecutor()

    if not cfg.safety.cleared_for_live:
        logger.error(
            "Refusing to trade live: --live was passed but LIVE_TRADING=true and "
            "I_UNDERSTAND_THE_RISK=yes are not both set in your .env. Falling back to dry run."
        )
        return DryRunExecutor()

    if not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set; falling back to dry run.")
        return DryRunExecutor()

    try:
        keypair = load_keypair(cfg.solana)
    except WalletError as exc:
        logger.error("Wallet error, falling back to dry run: %s", exc)
        return DryRunExecutor()

    logger.warning(
        "LIVE TRADING ENABLED. Wallet %s will send real transactions on pump.fun for mint %s.",
        keypair.pubkey(),
        cfg.trading.target_token_mint,
    )
    return PumpPortalExecutor(cfg.trading, keypair, cfg.solana.rpc_url)


def run_once(cfg, engine: SignalEngine, risk_manager: RiskManager, executor: TradeExecutor, history: MarketHistory, market) -> None:
    snapshot = market.fetch(cfg.trading.target_token_mint)
    features = history.push(snapshot)

    if len(history) < 2:
        logger.info("Warming up market history (%d/2 snapshots)...", len(history))
        return

    signal = engine.compute_signal(features)
    logger.info(
        "signal=%s score=%.3f confidence=%.3f price=$%.8f",
        signal.action.value,
        signal.score,
        signal.confidence,
        snapshot.price_usd,
    )

    planned = risk_manager.decide(signal, snapshot.price_usd)
    if planned.action == Action.HOLD:
        logger.info("HOLD (%s)", planned.reason)
        return

    result = executor.execute(planned, snapshot.price_usd)
    if not result.success:
        logger.error("Trade failed: %s", result.error)
        return

    risk_manager.record_fill(planned.action, result.filled_size_sol, result.price_usd)
    _log_trade_row(planned.action, result.filled_size_sol, result.price_usd, planned.reason, result.signature)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="memefly: fly-connectome-driven Solana meme coin trader")
    parser.add_argument("--live", action="store_true", help="Enable real order placement (also requires env safety switches).")
    parser.add_argument("--once", action="store_true", help="Run a single iteration instead of looping.")
    parser.add_argument("--interval", type=int, default=None, help="Override LOOP_INTERVAL_SECONDS.")
    parser.add_argument("--no-cache", action="store_true", help="Force a fresh neuPrint fetch instead of using the cache.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_config()

    try:
        graph = fetch_circuit(cfg.neuprint, use_cache=not args.no_cache)
    except ConnectomeError as exc:
        logger.error("Failed to load connectome circuit: %s", exc)
        return 1

    engine = SignalEngine(graph, cfg.signal)
    risk_manager = RiskManager(cfg.risk)
    executor = build_executor(args, cfg)
    market = DexscreenerProvider()
    history = MarketHistory()

    if not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set in .env.")
        return 1

    interval = args.interval or cfg.loop_interval_seconds

    try:
        while True:
            try:
                run_once(cfg, engine, risk_manager, executor, history, market)
            except Exception:  # noqa: BLE001
                logger.exception("Iteration failed, will retry next cycle.")
            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Stopped by user.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
