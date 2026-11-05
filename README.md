# Grok Trader v2 — Solana Paper Analyst

Solana new-token discovery, transparent market-quality scoring, and paper trading only.

## Safety
- Real trading is disabled. No wallet, private key, signing, or transaction submission is used.
- The market score is **not** a token-security audit. Security remains UNVERIFIED until independent on-chain checks are implemented.
- Stop-losses are checked each polling cycle and are not guaranteed execution prices. Fast crashes or missing liquidity can cause much larger simulated losses.
- DexScreener latest token profiles are discovery signals, not a complete launch feed.

## Termux
```bash
pkg update -y
pkg install python git -y
git clone -b termux-paper-mvp https://github.com/benedick3432/grok-trader.git
cd grok-trader
pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python bot.py
```

If the folder already exists, run `git pull origin termux-paper-mvp` inside it. Stop with Ctrl+C.

## Initial experimental paper rules
- Minimum liquidity: $15,000
- Minimum 5-minute volume: $10,000
- Minimum 5-minute transactions: 20
- Minimum market score: 70/100
- Maximum open positions: 3
- Re-entry cooldown after a sale: 60 minutes
- Daily realized-loss pause: $30
- Paper position size: $25

These are experimental filters, not profitable settings. Evaluate over a multi-week paper test.

Open positions are monitored independently of the discovery feed. Existing SQLite paper history is retained. Daily loss pause blocks new buys but continues monitoring open positions.
