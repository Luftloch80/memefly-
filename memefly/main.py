"""CLI entry point: python -m memefly.main [--live] [--once] [--interval N]

Safety: going live requires ALL THREE of:
  1. the --live CLI flag (explicit, per-invocation)
  2. LIVE_TRADING=true in the environment/.env
  3. I_UNDERSTAND_THE_RISK=yes in the environment/.env
Missing any one of these falls back to dry-run, no exceptions.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from memefly import state_store
from memefly.config import load_config
from memefly.connectome import CircuitGraph, ConnectomeError, fetch_circuit
from memefly.market_data import DexscreenerProvider, MarketHistory
from memefly.risk_manager import RiskManager
from memefly.signal_engine import Action, SignalEngine
from memefly.trader import DryRunExecutor, PumpPortalExecutor, TradeExecutor
from memefly.wallet import WalletError, load_keypair

logger = logging.getLogger("memefly")


def build_executor(args: argparse.Namespace, cfg) -> tuple[TradeExecutor, bool, str | None]:
    """Returns (executor, is_live, wallet_pubkey)."""
    if not args.live:
        logger.info("Running in DRY RUN mode (pass --live plus env safety switches for real trades).")
        return DryRunExecutor(), False, _try_pubkey(cfg)

    if not cfg.safety.cleared_for_live:
        logger.error(
            "Refusing to trade live: --live was passed but LIVE_TRADING=true and "
            "I_UNDERSTAND_THE_RISK=yes are not both set in your .env. Falling back to dry run."
        )
        return DryRunExecutor(), False, _try_pubkey(cfg)

    if not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set; falling back to dry run.")
        return DryRunExecutor(), False, _try_pubkey(cfg)

    try:
        keypair = load_keypair(cfg.solana)
    except WalletError as exc:
        logger.error("Wallet error, falling back to dry run: %s", exc)
        return DryRunExecutor(), False, None

    logger.warning(
        "LIVE TRADING ENABLED. Wallet %s will send real transactions on pump.fun for mint %s.",
        keypair.pubkey(),
        cfg.trading.target_token_mint,
    )
    return PumpPortalExecutor(cfg.trading, keypair, cfg.solana.rpc_url), True, str(keypair.pubkey())


def _try_pubkey(cfg) -> str | None:
    """Best-effort pubkey lookup for the dashboard even when not trading live."""
    try:
        return str(load_keypair(cfg.solana).pubkey())
    except WalletError:
        return None


def run_once(
    cfg,
    engine: SignalEngine,
    risk_manager: RiskManager,
    executor: TradeExecutor,
    history: MarketHistory,
    market,
    graph: CircuitGraph,
    is_live: bool,
    wallet_pubkey: str | None,
) -> None:
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

    signature = None
    if planned.action != Action.HOLD:
        result = executor.execute(planned, snapshot.price_usd)
        if result.success:
            risk_manager.record_fill(planned.action, result.filled_size_sol, result.price_usd)
            signature = result.signature
            state_store.append_trade(
                planned.action.value, result.filled_size_sol, result.price_usd, planned.reason, signature
            )
        else:
            logger.error("Trade failed: %s", result.error)
    else:
        logger.info("HOLD (%s)", planned.reason)

    s = risk_manager.state
    state_store.record_activity(
        state_store.ActivityRow(
            timestamp=time.time(),
            price_usd=snapshot.price_usd,
            action=signal.action.value,
            score=signal.score,
            confidence=signal.confidence,
            approach_spikes=signal.approach_spikes,
            avoidance_spikes=signal.avoidance_spikes,
            reason=planned.reason,
            position_sol=s.position_sol,
            daily_pnl_sol=s.daily_pnl_sol,
            halted=s.halted,
        )
    )
    state_store.write_state(
        {
            "timestamp": time.time(),
            "is_live": is_live,
            "wallet_pubkey": wallet_pubkey,
            "target_token_mint": cfg.trading.target_token_mint,
            "solana_rpc_url": cfg.solana.rpc_url,
            "price_usd": snapshot.price_usd,
            "position_sol": s.position_sol,
            "entry_price_usd": s.entry_price_usd,
            "daily_pnl_sol": s.daily_pnl_sol,
            "halted": s.halted,
            "halt_reason": s.halt_reason,
            "last_trade_signature": signature,
            "signal": {
                "action": signal.action.value,
                "score": signal.score,
                "confidence": signal.confidence,
                "approach_spikes": signal.approach_spikes,
                "avoidance_spikes": signal.avoidance_spikes,
                "approach_neuron_spikes": list(signal.approach_neuron_spikes),
                "avoidance_neuron_spikes": list(signal.avoidance_neuron_spikes),
            },
            "circuit": {
                "dataset": cfg.neuprint.dataset,
                "num_neurons": len(graph.body_ids),
                "num_input_neurons": len(graph.input_indices),
                "num_output_neurons": len(graph.output_indices),
            },
        }
    )


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
    executor, is_live, wallet_pubkey = build_executor(args, cfg)
    market = DexscreenerProvider()
    history = MarketHistory()

    if not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set in .env.")
        return 1

    interval = args.interval or cfg.loop_interval_seconds

    try:
        while True:
            try:
                run_once(cfg, engine, risk_manager, executor, history, market, graph, is_live, wallet_pubkey)
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
