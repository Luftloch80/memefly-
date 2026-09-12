"""Loads all runtime configuration from environment variables (.env).

Nothing in here should ever be hardcoded with a real secret. SOLANA_PRIVATE_KEY
and NEUPRINT_TOKEN are read from the environment only and are never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass(frozen=True)
class NeuprintConfig:
    server: str = field(default_factory=lambda: os.getenv("NEUPRINT_SERVER", "https://neuprint.janelia.org"))
    dataset: str = field(default_factory=lambda: os.getenv("NEUPRINT_DATASET", "hemibrain:v1.2.1"))
    token: str = field(default_factory=lambda: os.getenv("NEUPRINT_TOKEN", ""))
    input_type_regex: str = field(default_factory=lambda: os.getenv("NEUPRINT_INPUT_TYPE_REGEX", ".*PN.*"))
    output_type_regex: str = field(default_factory=lambda: os.getenv("NEUPRINT_OUTPUT_TYPE_REGEX", ".*MBON.*"))
    max_neurons: int = field(default_factory=lambda: _get_int("NEUPRINT_MAX_NEURONS", 400))


@dataclass(frozen=True)
class SolanaConfig:
    private_key: str = field(default_factory=lambda: os.getenv("SOLANA_PRIVATE_KEY", ""))
    keypair_path: str = field(default_factory=lambda: os.getenv("SOLANA_KEYPAIR_PATH", ""))
    rpc_url: str = field(default_factory=lambda: os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))


@dataclass(frozen=True)
class TradingConfig:
    target_token_mint: str = field(default_factory=lambda: os.getenv("TARGET_TOKEN_MINT", ""))
    pumpportal_pool: str = field(default_factory=lambda: os.getenv("PUMPPORTAL_POOL", "pump"))
    pumpportal_api_url: str = field(
        default_factory=lambda: os.getenv("PUMPPORTAL_API_URL", "https://pumpportal.fun/api/trade-local")
    )
    slippage_pct: float = field(default_factory=lambda: _get_float("PUMPPORTAL_SLIPPAGE_PCT", 10.0))
    priority_fee_sol: float = field(default_factory=lambda: _get_float("PUMPPORTAL_PRIORITY_FEE_SOL", 0.0005))


@dataclass(frozen=True)
class RiskConfig:
    max_trade_sol: float = field(default_factory=lambda: _get_float("MAX_TRADE_SOL", 0.05))
    max_position_sol: float = field(default_factory=lambda: _get_float("MAX_POSITION_SOL", 0.2))
    max_daily_loss_sol: float = field(default_factory=lambda: _get_float("MAX_DAILY_LOSS_SOL", 0.3))
    cooldown_seconds: int = field(default_factory=lambda: _get_int("COOLDOWN_SECONDS", 300))
    stop_loss_pct: float = field(default_factory=lambda: _get_float("STOP_LOSS_PCT", 0.25))
    take_profit_pct: float = field(default_factory=lambda: _get_float("TAKE_PROFIT_PCT", 0.5))


@dataclass(frozen=True)
class DiscoveryConfig:
    """Autonomous coin discovery: instead of trading a fixed
    TARGET_TOKEN_MINT, the bot watches PumpPortal's live feed of newly
    created pump.fun tokens and picks which one (if any) to buy using the
    same connectome signal. Off by default -- this is materially riskier
    than trading a coin you picked yourself, since most brand-new pump.fun
    tokens are rugs. The age/trade-count filters reduce, but do not
    eliminate, that risk.
    """

    enabled: bool = field(default_factory=lambda: _get_bool("DISCOVERY_MODE", False))
    ws_url: str = field(default_factory=lambda: os.getenv("DISCOVERY_WS_URL", "wss://pumpportal.fun/api/data"))
    min_age_seconds: int = field(default_factory=lambda: _get_int("DISCOVERY_MIN_AGE_SECONDS", 300))
    max_age_seconds: int = field(default_factory=lambda: _get_int("DISCOVERY_MAX_AGE_SECONDS", 3600))
    min_trades: int = field(default_factory=lambda: _get_int("DISCOVERY_MIN_TRADES", 20))
    max_candidates: int = field(default_factory=lambda: _get_int("DISCOVERY_MAX_CANDIDATES", 30))


@dataclass(frozen=True)
class SignalConfig:
    buy_threshold: float = field(default_factory=lambda: _get_float("BUY_THRESHOLD", 0.2))
    sell_threshold: float = field(default_factory=lambda: _get_float("SELL_THRESHOLD", -0.2))


@dataclass(frozen=True)
class SafetyConfig:
    live_trading: bool = field(default_factory=lambda: _get_bool("LIVE_TRADING", False))
    risk_acknowledged: bool = field(
        default_factory=lambda: os.getenv("I_UNDERSTAND_THE_RISK", "no").strip().lower() == "yes"
    )

    @property
    def cleared_for_live(self) -> bool:
        return self.live_trading and self.risk_acknowledged


@dataclass(frozen=True)
class Config:
    neuprint: NeuprintConfig = field(default_factory=NeuprintConfig)
    solana: SolanaConfig = field(default_factory=SolanaConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    loop_interval_seconds: int = field(default_factory=lambda: _get_int("LOOP_INTERVAL_SECONDS", 60))


def load_config() -> Config:
    return Config()
