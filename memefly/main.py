"""CLI entry point: python -m memefly.main [--live] [--once] [--interval N]

Safety: going live requires ALL THREE of:
  1. the --live CLI flag (explicit, per-invocation)
  2. LIVE_TRADING=true in the environment/.env
  3. I_UNDERSTAND_THE_RISK=yes in the environment/.env
Missing any one of these falls back to dry-run, no exceptions.

Two trading modes, chosen by DISCOVERY_MODE in .env:
  - classic (default): trades the single coin in TARGET_TOKEN_MINT.
  - discovery: watches PumpPortal's live feed of newly created pump.fun
    tokens, scores every candidate that clears the age/trade-count
    filters with the same connectome signal, and buys the best one.
    Materially riskier than classic mode -- see README.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from memefly import state_store
from memefly.config import load_config
from memefly.connectome import CircuitGraph, ConnectomeError, fetch_circuit
from memefly.discovery import CandidateRegistry, PumpPortalTokenFeed
from memefly.market_data import DexscreenerProvider, MarketHistory, MarketSnapshot
from memefly.risk_manager import PlannedTrade, RiskManager
from memefly.signal_engine import Action, SignalEngine, TradeSignal
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

    if not cfg.discovery.enabled and not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set; falling back to dry run.")
        return DryRunExecutor(), False, _try_pubkey(cfg)

    try:
        keypair = load_keypair(cfg.solana)
    except WalletError as exc:
        logger.error("Wallet error, falling back to dry run: %s", exc)
        return DryRunExecutor(), False, None

    logger.warning(
        "LIVE TRADING ENABLED. Wallet %s will send real transactions on pump.fun.%s",
        keypair.pubkey(),
        "" if cfg.discovery.enabled else f" mint={cfg.trading.target_token_mint}",
    )
    return PumpPortalExecutor(cfg.trading, keypair, cfg.solana.rpc_url), True, str(keypair.pubkey())


def _try_pubkey(cfg) -> str | None:
    """Best-effort pubkey lookup for the dashboard even when not trading live."""
    try:
        return str(load_keypair(cfg.solana).pubkey())
    except WalletError:
        return None


def _execute_and_persist(
    cfg,
    risk_manager: RiskManager,
    executor: TradeExecutor,
    graph: CircuitGraph,
    is_live: bool,
    wallet_pubkey: str | None,
    mint: str,
    price: float,
    signal: TradeSignal,
    planned: PlannedTrade,
    mode: str,
    candidates: list[dict] | None = None,
) -> None:
    signature = None
    if planned.action != Action.HOLD:
        result = executor.execute(planned, price)
        if result.success:
            risk_manager.record_fill(planned.action, result.filled_size_sol, result.price_usd, mint=mint)
            signature = result.signature
            state_store.append_trade(
                planned.action.value, result.filled_size_sol, result.price_usd, planned.reason, signature, mint=mint
            )
        else:
            logger.error("Trade failed: %s", result.error)
    else:
        logger.info("HOLD (%s)", planned.reason)

    s = risk_manager.state
    state_store.record_activity(
        state_store.ActivityRow(
            timestamp=time.time(),
            mint=mint,
            price_usd=price,
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
            "mode": mode,
            "price_unit": "sol" if mode == "discovery" else "usd",
            "is_live": is_live,
            "wallet_pubkey": wallet_pubkey,
            "target_token_mint": mint,
            "held_mint": s.held_mint,
            "solana_rpc_url": cfg.solana.rpc_url,
            "price_usd": price,
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
            "candidates": candidates or [],
        }
    )


def run_once_fixed(
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
    mint = cfg.trading.target_token_mint
    snapshot = market.fetch(mint)
    features = history.push(snapshot)

    if len(history) < 2:
        logger.info("Warming up market history (%d/2 snapshots)...", len(history))
        return

    signal = engine.compute_signal(features)
    logger.info(
        "signal=%s score=%.3f confidence=%.3f price=$%.8f", signal.action.value, signal.score, signal.confidence, snapshot.price_usd
    )
    planned = risk_manager.decide(signal, snapshot.price_usd)
    _execute_and_persist(cfg, risk_manager, executor, graph, is_live, wallet_pubkey, mint, snapshot.price_usd, signal, planned, mode="fixed")


def run_once_discovery(
    cfg,
    engine: SignalEngine,
    risk_manager: RiskManager,
    executor: TradeExecutor,
    graph: CircuitGraph,
    is_live: bool,
    wallet_pubkey: str | None,
    feed: PumpPortalTokenFeed,
    histories: dict[str, MarketHistory],
) -> None:
    now = time.time()
    s = risk_manager.state
    dc = cfg.discovery

    if s.held_mint:
        held = feed.registry.get(s.held_mint)
        if held is None:
            logger.warning("Held mint %s dropped out of the feed registry; can't get a price update this cycle.", s.held_mint)
            return
        history = histories.setdefault(s.held_mint, MarketHistory())
        features = history.push(MarketSnapshot(price_usd=held.price_sol, volume_24h_usd=float(held.trade_count), timestamp=now))
        if len(history) < 2:
            return
        signal = engine.compute_signal(features)
        planned = risk_manager.decide(signal, held.price_sol, mint=s.held_mint)
        logger.info("held=%s signal=%s score=%.3f price=%.10f SOL", s.held_mint, signal.action.value, signal.score, held.price_sol)
        _execute_and_persist(
            cfg, risk_manager, executor, graph, is_live, wallet_pubkey, s.held_mint, held.price_sol, signal, planned, mode="discovery"
        )
        return

    feed.registry.prune(now, dc.max_age_seconds, dc.max_candidates)
    raw_candidates = feed.registry.get_candidates(now, dc.min_age_seconds, dc.max_age_seconds, dc.min_trades)

    tracked_mints = {c.mint for c in raw_candidates}
    for stale_mint in set(histories) - tracked_mints:
        del histories[stale_mint]

    best_signal: TradeSignal | None = None
    best_mint: str | None = None
    best_price = 0.0
    summary: list[dict] = []

    for c in raw_candidates:
        history = histories.setdefault(c.mint, MarketHistory())
        features = history.push(MarketSnapshot(price_usd=c.price_sol, volume_24h_usd=float(c.trade_count), timestamp=now))
        if len(history) < 2:
            continue
        sig = engine.compute_signal(features)
        summary.append(
            {
                "mint": c.mint,
                "symbol": c.symbol,
                "action": sig.action.value,
                "score": sig.score,
                "confidence": sig.confidence,
                "trade_count": c.trade_count,
                "age_seconds": now - c.created_at,
            }
        )
        if sig.action == Action.BUY:
            rank = sig.score * sig.confidence
            if best_signal is None or rank > best_signal.score * best_signal.confidence:
                best_signal, best_mint, best_price = sig, c.mint, c.price_sol

    summary.sort(key=lambda x: x["score"] * x["confidence"], reverse=True)
    logger.info("Discovery: %d tokens tracked, %d evaluated, best=%s", feed.registry.size(), len(summary), best_mint)

    if best_mint is None:
        no_signal = TradeSignal(action=Action.HOLD, score=0.0, confidence=0.0, approach_spikes=0.0, avoidance_spikes=0.0)
        no_trade = PlannedTrade(Action.HOLD, 0.0, "no_buy_candidate")
        _execute_and_persist(cfg, risk_manager, executor, graph, is_live, wallet_pubkey, "", 0.0, no_signal, no_trade, mode="discovery", candidates=summary[:20])
        return

    planned = risk_manager.decide(best_signal, best_price, mint=best_mint)
    _execute_and_persist(
        cfg, risk_manager, executor, graph, is_live, wallet_pubkey, best_mint, best_price, best_signal, planned, mode="discovery", candidates=summary[:20]
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
    interval = args.interval or cfg.loop_interval_seconds

    if cfg.discovery.enabled:
        logger.warning(
            "DISCOVERY_MODE is enabled: the bot will autonomously pick which newly "
            "created pump.fun token to buy. Most brand-new tokens are rugs -- see "
            "the README before running this live."
        )
        feed = PumpPortalTokenFeed(cfg.discovery, protected_mint_getter=lambda: risk_manager.state.held_mint)
        feed.start()
        histories: dict[str, MarketHistory] = {}

        try:
            while True:
                try:
                    run_once_discovery(cfg, engine, risk_manager, executor, graph, is_live, wallet_pubkey, feed, histories)
                except Exception:  # noqa: BLE001
                    logger.exception("Iteration failed, will retry next cycle.")
                if args.once:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
        finally:
            feed.stop()
        return 0

    if not cfg.trading.target_token_mint:
        logger.error("TARGET_TOKEN_MINT is not set in .env (or set DISCOVERY_MODE=true to trade autonomously).")
        return 1

    market = DexscreenerProvider()
    history = MarketHistory()

    try:
        while True:
            try:
                run_once_fixed(cfg, engine, risk_manager, executor, history, market, graph, is_live, wallet_pubkey)
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
