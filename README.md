# memefly

A real fruit fly brain circuit, pulled from Google/HHMI Janelia's public
fly connectome data (via [neuPrint](https://neuprint.janelia.org)), wired
up to trade meme coins on Solana through [pump.fun](https://pump.fun).

Market data (price, volume) is fed into the connectome's real sensory
input neurons as simulated "current." The resulting spiking activity in a
real downstream circuit (by default, antennal-lobe projection neurons →
mushroom-body output neurons from the hemibrain dataset) is read out as a
buy / sell / hold signal.

## Read this before you fund a wallet

- **This is a novelty project, not a trading strategy with edge.** There
  is no causal or evolutionary link between fly olfaction and Solana meme
  coin prices. The connectome is real; the simulation is a real dynamical
  system; but mapping "price change" onto "odor concentration" is an
  arbitrary reinterpretation, not a discovered signal. Expect the output
  to behave like noise.
- **Meme coins, and pump.fun tokens especially, are extremely volatile
  and commonly subject to rug pulls, pulled liquidity, and outright
  scams.** Assume you can lose 100% of anything this bot trades with.
- **Only fund the wallet you point at this with an amount you are fully
  prepared to lose**, and nothing else. Do not reuse a wallet that holds
  other assets.
- Third-party APIs this project depends on (pump.fun/PumpPortal,
  Dexscreener) are unofficial/community and can change or go down without
  notice — verify current request/response shapes before relying on this.

None of this is financial advice.

## Safety design

- **Dry-run by default.** Without the `--live` CLI flag *and*
  `LIVE_TRADING=true` *and* `I_UNDERSTAND_THE_RISK=yes` in `.env`, no
  order is ever placed — the bot only logs what it would have done.
- **Your private key never leaves your machine.** It's read from a local
  `.env` file or keypair file (both gitignored), used only to sign
  transactions locally, and is never logged, printed, or sent to any API
  — PumpPortal receives only the unsigned transaction request, and the
  signed transaction is submitted directly to your configured Solana RPC.
- **Hard risk limits enforced in code**, independent of whatever the
  signal says: max SOL per trade, max total position size, a cooldown
  between trades, per-position stop-loss / take-profit, and a daily-loss
  kill switch that halts all trading once tripped.

## Architecture

```
market_data.py   -- fetch price/volume (Dexscreener), rolling features
connectome.py    -- fetch a real neuPrint circuit, cache it, LIF simulation
signal_engine.py -- market features -> neural input -> buy/sell/hold + confidence
risk_manager.py  -- position sizing, cooldown, stop-loss/take-profit, kill switch
trader.py        -- DryRunExecutor (default) / PumpPortalExecutor (real orders)
wallet.py        -- local keypair loading
state_store.py   -- state.json / activity_log.csv / trade_log.csv shared with the dashboard
main.py          -- CLI + the loop tying it all together
dashboard.py     -- read-only Flask web dashboard (templates/, static/)

panel/           -- local control panel: edit .env, build/start/stop Docker (see below)
Dockerfile, entrypoint.sh, docker-compose.yml, .dockerignore
```

## Setup

1. **Get a neuPrint token** (free): sign in at
   https://neuprint.janelia.org, open your account menu, copy your Auth
   Token.
2. **Create a Solana wallet** dedicated to this bot (e.g. via
   `solana-keygen new` or exporting a fresh Phantom wallet's private key).
   Fund it with only what you're willing to lose.
3. **Copy the env template and fill it in:**
   ```
   cp .env.example .env
   ```
   Set `NEUPRINT_TOKEN`, `SOLANA_PRIVATE_KEY` (or `SOLANA_KEYPAIR_PATH`),
   `TARGET_TOKEN_MINT` (the mint address of the pump.fun token to trade),
   and review the risk limits.
4. **Install dependencies:**
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. **Run the tests** (no network or credentials required):
   ```
   pytest
   ```

## Running

Dry run, single iteration (safe, no orders placed, no real API calls to
pump.fun):
```
python -m memefly.main --once
```

Dry run, looping every `LOOP_INTERVAL_SECONDS`:
```
python -m memefly.main
```

Live trading (only works if `.env` has `LIVE_TRADING=true` and
`I_UNDERSTAND_THE_RISK=yes` — otherwise it silently falls back to dry
run):
```
python -m memefly.main --live
```

Trades (real or dry-run) are appended to `trade_log.csv` (gitignored).
Every iteration (trade or not) also updates `state.json` and appends to
`activity_log.csv` (also gitignored) — that's what the dashboard reads.

## Dashboard

A stylish, read-only web UI showing wallet balance, open position, daily
PnL, price/PnL history, which "brain cells" (output neurons) fired
approach vs. avoidance spikes for the latest signal, and a table of
recent trades with Solscan links.

It runs as its **own process**, separate from the trading loop, and only
talks to it through the local `state.json` / `activity_log.csv` /
`trade_log.csv` files — it never signs or sends transactions. The one
live network call it makes is a public, read-only `getBalance` RPC
lookup for your wallet's balance.

Run the trading loop in one terminal:
```
python -m memefly.main
```

And the dashboard in another:
```
python -m memefly.dashboard
```
Then open http://127.0.0.1:8765. It auto-refreshes every 5 seconds.
Pass `--host`/`--port` to change where it listens.

## Running on a Raspberry Pi with Docker

The `Dockerfile` uses `python:3.11-slim`, which is multi-arch — building it
**on the Pi itself** produces a native arm64 (or armv7) image with no
cross-compilation setup. A modern 64-bit Raspberry Pi OS (Bookworm, Pi 4/5,
2GB+ RAM) is recommended; some dependencies (e.g. `solders`) may not have
prebuilt wheels for 32-bit armv7, in which case pip will need to compile
them from source, which is slow on a Pi and may need a Rust toolchain
added to the Dockerfile.

1. **Install Docker + Compose on the Pi** (if not already):
   ```
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out/in after this
   ```
2. **Get the code onto the Pi** (clone the repo) and `cd` into it.
3. **Run the control panel** (plain Python, not containerized — it's the
   thing that builds/runs the containers, so it stays on the host):
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install flask python-dotenv
   python -m panel.app
   ```
   It prints a URL with an access token, e.g.
   `http://127.0.0.1:8766/?token=...`. Open that in a browser on the Pi,
   or tunnel/forward the port over SSH if you're working from another
   machine — don't expose this port on your LAN or the internet as-is,
   since anyone with the URL can overwrite your `.env` and trigger builds.
4. **Fill in the form** (neuPrint token, Solana wallet, target token
   mint, risk limits, safety switches) and click **Save Settings** — this
   writes `.env` (0600 permissions, gitignored, never sent anywhere else).
5. Click **Build Image** — runs `docker compose build` and streams the
   log. Then **Start** — runs `docker compose up -d`, launching the `bot`
   and `dashboard` containers, sharing a Docker volume for `state.json` /
   the logs / the connectome cache. **Stop** runs `docker compose down`.
6. Once running, the trading-loop dashboard from the section above is at
   `http://<pi-address>:8765/`.

The bot container's `entrypoint.sh` re-checks `LIVE_TRADING` and
`I_UNDERSTAND_THE_RISK` itself before ever adding `--live` to its command
— the same two switches gate live trading whether you run this in Docker
or directly with `python -m memefly.main`.

You can skip the panel entirely and drive Compose by hand if you prefer:
```
cp .env.example .env   # fill it in
docker compose build
docker compose up -d
docker compose logs -f
docker compose down
```

## Changing the circuit

`NEUPRINT_INPUT_TYPE_REGEX` / `NEUPRINT_OUTPUT_TYPE_REGEX` in `.env`
control which neuron types are pulled as the "sensory input" and
"decision output" populations. The default (`PN` → `MBON` on
`hemibrain:v1.2.1`) is a real, well-studied olfactory-to-behavior
pathway. The fetched circuit is cached under `.cache/connectome/` after
the first run; delete that file (or pass `--no-cache`) to re-fetch.
