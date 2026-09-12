"""Declarative description of every .env field the control panel edits.

Keeping this as one list (instead of a hand-written HTML form) means the
form, the merge-on-save logic, and .env.example can't drift out of sync.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldDef:
    name: str
    label: str
    section: str
    type: str = "text"  # text | password | number | checkbox | select
    default: str = ""
    help: str = ""
    options: tuple[str, ...] = ()
    step: str | None = None
    on_value: str = "true"
    off_value: str = "false"


FIELDS: list[FieldDef] = [
    # --- neuPrint ---
    FieldDef(
        "NEUPRINT_TOKEN", "neuPrint Auth Token", "neuPrint (fly connectome)",
        type="password",
        help="Free token from neuprint.janelia.org -> account menu -> Auth Token.",
    ),
    FieldDef("NEUPRINT_SERVER", "neuPrint Server", "neuPrint (fly connectome)", default="https://neuprint.janelia.org"),
    FieldDef("NEUPRINT_DATASET", "Dataset", "neuPrint (fly connectome)", default="hemibrain:v1.2.1"),
    FieldDef("NEUPRINT_INPUT_TYPE_REGEX", "Input Neuron Type Regex", "neuPrint (fly connectome)", default=".*PN.*"),
    FieldDef("NEUPRINT_OUTPUT_TYPE_REGEX", "Output Neuron Type Regex", "neuPrint (fly connectome)", default=".*MBON.*"),
    FieldDef("NEUPRINT_MAX_NEURONS", "Max Neurons", "neuPrint (fly connectome)", type="number", default="400"),

    # --- Solana wallet ---
    FieldDef(
        "SOLANA_PRIVATE_KEY", "Solana Private Key (base58)", "Solana wallet",
        type="password",
        help="Use a wallet dedicated to this bot, funded only with what you can afford to lose. Leave blank to keep the saved key.",
    ),
    FieldDef("SOLANA_KEYPAIR_PATH", "...or Keypair File Path", "Solana wallet", help="Alternative to the field above: a path to a JSON keypair file."),
    FieldDef("SOLANA_RPC_URL", "Solana RPC URL", "Solana wallet", default="https://api.mainnet-beta.solana.com"),

    # --- Trading target ---
    FieldDef(
        "DISCOVERY_MODE", "Autonomous Discovery", "Trading target",
        type="checkbox", default="false",
        help="OFF (default): trade only the fixed Target Token Mint below. ON: ignore the mint below and let the bot pick which brand-new pump.fun coin to buy using the connectome signal. Materially riskier -- most new coins are rugs.",
    ),
    FieldDef("TARGET_TOKEN_MINT", "Target Token Mint", "Trading target", help="The pump.fun token mint address to trade. Ignored when Autonomous Discovery is on."),
    FieldDef("PUMPPORTAL_POOL", "Pool", "Trading target", type="select", default="pump", options=("pump", "raydium", "auto")),
    FieldDef("PUMPPORTAL_API_URL", "PumpPortal API URL", "Trading target", default="https://pumpportal.fun/api/trade-local"),
    FieldDef("PUMPPORTAL_SLIPPAGE_PCT", "Slippage %", "Trading target", type="number", default="10", step="0.1"),
    FieldDef("PUMPPORTAL_PRIORITY_FEE_SOL", "Priority Fee (SOL)", "Trading target", type="number", default="0.0005", step="0.0001"),

    # --- Discovery filters (only used when Autonomous Discovery is on) ---
    FieldDef("DISCOVERY_WS_URL", "PumpPortal WebSocket URL", "Discovery filters", default="wss://pumpportal.fun/api/data"),
    FieldDef("DISCOVERY_MIN_AGE_SECONDS", "Min Coin Age Before Considering (s)", "Discovery filters", type="number", default="300"),
    FieldDef("DISCOVERY_MAX_AGE_SECONDS", "Max Coin Age Before Ignoring (s)", "Discovery filters", type="number", default="3600"),
    FieldDef("DISCOVERY_MIN_TRADES", "Min Trades Before Considering", "Discovery filters", type="number", default="20"),
    FieldDef("DISCOVERY_MAX_CANDIDATES", "Max Candidates Tracked at Once", "Discovery filters", type="number", default="30"),

    # --- Risk limits ---
    FieldDef("MAX_TRADE_SOL", "Max SOL per Trade", "Risk limits (SOL)", type="number", default="0.05", step="0.001"),
    FieldDef("MAX_POSITION_SOL", "Max Total Position", "Risk limits (SOL)", type="number", default="0.2", step="0.001"),
    FieldDef("MAX_DAILY_LOSS_SOL", "Max Daily Loss (kill switch)", "Risk limits (SOL)", type="number", default="0.3", step="0.001"),
    FieldDef("COOLDOWN_SECONDS", "Cooldown Between Trades (s)", "Risk limits (SOL)", type="number", default="300"),
    FieldDef("STOP_LOSS_PCT", "Stop Loss (fraction, e.g. 0.25)", "Risk limits (SOL)", type="number", default="0.25", step="0.01"),
    FieldDef("TAKE_PROFIT_PCT", "Take Profit (fraction, e.g. 0.5)", "Risk limits (SOL)", type="number", default="0.5", step="0.01"),

    # --- Signal thresholds ---
    FieldDef("BUY_THRESHOLD", "Buy Threshold (score >=)", "Signal thresholds", type="number", default="0.2", step="0.01"),
    FieldDef("SELL_THRESHOLD", "Sell Threshold (score <=)", "Signal thresholds", type="number", default="-0.2", step="0.01"),

    # --- Loop ---
    FieldDef("LOOP_INTERVAL_SECONDS", "Loop Interval (s)", "Loop", type="number", default="60"),

    # --- Safety switches ---
    FieldDef(
        "LIVE_TRADING", "Enable Live Trading", "Safety switches",
        type="checkbox", default="false",
        help="Both this AND the acknowledgement below must be on, or the bot container stays in dry-run no matter what.",
    ),
    FieldDef(
        "I_UNDERSTAND_THE_RISK", "I Understand The Risk", "Safety switches",
        type="checkbox", default="no", on_value="yes", off_value="no",
        help="Meme coins are extremely volatile and this signal is a novelty, not a strategy with edge. You can lose everything you fund the wallet with.",
    ),
]

SECRET_FIELDS = frozenset(f.name for f in FIELDS if f.type == "password")
CHECKBOX_FIELDS = {f.name: f for f in FIELDS if f.type == "checkbox"}
FIELDS_BY_NAME = {f.name: f for f in FIELDS}


def sections() -> list[str]:
    seen: list[str] = []
    for f in FIELDS:
        if f.section not in seen:
            seen.append(f.section)
    return seen
