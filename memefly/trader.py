"""Trade execution backends.

DryRunExecutor never touches the network for order placement -- it just
logs what would have happened and lets the risk manager track a
hypothetical position, which is why it's the default.

PumpPortalExecutor talks to pump.fun's community "local trading" API
(https://pumpportal.fun/local-trading-api): PumpPortal builds an unsigned
transaction for the swap, we sign it locally with the user's own keypair,
and we submit the signed transaction directly to a Solana RPC endpoint.
The private key never leaves this process -- it is not sent to PumpPortal
or anywhere else. Verify the current request/response shape against
PumpPortal's docs before relying on this in production; third-party APIs
like this change without notice.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Protocol

import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from memefly.config import TradingConfig
from memefly.risk_manager import PlannedTrade
from memefly.signal_engine import Action

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeResult:
    success: bool
    signature: str | None
    filled_size_sol: float
    price_usd: float
    error: str | None = None
    mint: str | None = None


class TradeExecutor(Protocol):
    def execute(self, planned: PlannedTrade, current_price_usd: float) -> TradeResult: ...


class DryRunExecutor:
    def execute(self, planned: PlannedTrade, current_price_usd: float) -> TradeResult:
        logger.info(
            "[DRY RUN] would %s %.6f SOL at ~$%.8f (%s)",
            planned.action.value,
            planned.size_sol,
            current_price_usd,
            planned.reason,
        )
        return TradeResult(
            success=True,
            signature=None,
            filled_size_sol=planned.size_sol,
            price_usd=current_price_usd,
            mint=planned.mint,
        )


class PumpPortalExecutor:
    """`config.target_token_mint` is only a fallback for the classic
    fixed-mint mode. In discovery mode, `planned.mint` (set by the risk
    manager per candidate) is what actually gets traded.
    """

    def __init__(self, config: TradingConfig, keypair: Keypair, rpc_url: str, timeout_seconds: float = 20.0) -> None:
        self.config = config
        self.keypair = keypair
        self.rpc_url = rpc_url
        self.timeout_seconds = timeout_seconds

    def execute(self, planned: PlannedTrade, current_price_usd: float) -> TradeResult:
        if planned.action == Action.HOLD or planned.size_sol <= 0:
            return TradeResult(True, None, 0.0, current_price_usd, mint=planned.mint)

        mint = planned.mint or self.config.target_token_mint
        if not mint:
            return TradeResult(False, None, 0.0, current_price_usd, error="no target mint specified", mint=None)

        payload = {
            "publicKey": str(self.keypair.pubkey()),
            "action": planned.action.value,  # "buy" or "sell"
            "mint": mint,
            "amount": planned.size_sol,
            "denominatedInSol": "true",
            "slippage": self.config.slippage_pct,
            "priorityFee": self.config.priority_fee_sol,
            "pool": self.config.pumpportal_pool,
        }

        try:
            resp = requests.post(self.config.pumpportal_api_url, data=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            unsigned_tx = VersionedTransaction.from_bytes(resp.content)
            signed_tx = VersionedTransaction(unsigned_tx.message, [self.keypair])

            signature = self._send_raw_transaction(bytes(signed_tx))
            logger.info("Submitted %s of %.6f SOL for %s, signature=%s", planned.action.value, planned.size_sol, mint, signature)
            return TradeResult(True, signature, planned.size_sol, current_price_usd, mint=mint)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Trade execution failed")
            return TradeResult(False, None, 0.0, current_price_usd, error=str(exc), mint=mint)

    def _send_raw_transaction(self, raw_tx: bytes) -> str:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(raw_tx).decode("ascii"),
                {"encoding": "base64", "skipPreflight": False, "maxRetries": 3},
            ],
        }
        resp = requests.post(self.rpc_url, json=body, timeout=self.timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]
