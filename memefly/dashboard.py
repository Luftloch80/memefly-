"""Read-only web dashboard for the memefly trading loop.

Run the trading loop (memefly.main) in one process and this dashboard in
another -- they talk to each other only through the local state.json /
activity_log.csv / trade_log.csv files written by state_store.py. The
dashboard never signs or submits transactions; the one live network call
it makes is a public, read-only getBalance RPC request.
"""
from __future__ import annotations

import logging

import requests
from flask import Flask, jsonify, render_template

from memefly import state_store
from memefly.config import load_config

logger = logging.getLogger("memefly.dashboard")

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    state = state_store.read_state()
    if state is None:
        return jsonify({"error": "no state yet -- start memefly.main first"}), 404
    return jsonify(state)


@app.get("/api/history")
def api_history():
    from flask import request

    limit = min(int(request.args.get("limit", 200)), 2000)
    return jsonify(state_store.read_activity(limit=limit))


@app.get("/api/trades")
def api_trades():
    from flask import request

    limit = min(int(request.args.get("limit", 100)), 1000)
    return jsonify(state_store.read_trades(limit=limit))


@app.get("/api/balance")
def api_balance():
    state = state_store.read_state() or {}
    pubkey = state.get("wallet_pubkey")
    rpc_url = state.get("solana_rpc_url")

    if not pubkey or not rpc_url:
        cfg = load_config()
        rpc_url = rpc_url or cfg.solana.rpc_url
        if not pubkey:
            return jsonify({"balance_sol": None, "error": "no wallet configured"})

    try:
        resp = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        lamports = data["result"]["value"]
        return jsonify({"balance_sol": lamports / 1_000_000_000, "pubkey": pubkey})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Balance fetch failed: %s", exc)
        return jsonify({"balance_sol": None, "pubkey": pubkey, "error": str(exc)})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="memefly dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
