"""Local Solana keypair loading.

The private key is read from an environment variable or a local keypair
file and is never logged, printed, or included in any exception message.
"""
from __future__ import annotations

import json

from solders.keypair import Keypair

from memefly.config import SolanaConfig


class WalletError(Exception):
    pass


def load_keypair(cfg: SolanaConfig) -> Keypair:
    if cfg.private_key:
        try:
            return Keypair.from_base58_string(cfg.private_key.strip())
        except Exception as exc:  # noqa: BLE001 - never leak the key value
            raise WalletError("Could not parse SOLANA_PRIVATE_KEY (bad format).") from None

    if cfg.keypair_path:
        try:
            with open(cfg.keypair_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return Keypair.from_bytes(bytes(raw))
        except FileNotFoundError:
            raise WalletError(f"Keypair file not found: {cfg.keypair_path}") from None
        except Exception:
            raise WalletError("Could not parse the keypair file (expected a JSON byte array).") from None

    raise WalletError(
        "No wallet configured. Set SOLANA_PRIVATE_KEY or SOLANA_KEYPAIR_PATH in your .env."
    )
