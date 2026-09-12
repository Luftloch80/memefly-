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
main.py          -- CLI + the loop tying it all together
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

## Changing the circuit

`NEUPRINT_INPUT_TYPE_REGEX` / `NEUPRINT_OUTPUT_TYPE_REGEX` in `.env`
control which neuron types are pulled as the "sensory input" and
"decision output" populations. The default (`PN` → `MBON` on
`hemibrain:v1.2.1`) is a real, well-studied olfactory-to-behavior
pathway. The fetched circuit is cached under `.cache/connectome/` after
the first run; delete that file (or pass `--no-cache`) to re-fetch.
