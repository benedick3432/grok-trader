# Grok Trader v3 — Solana Fast-Loop Paper Analyst

Solana token discovery, transparent market-quality scoring, and paper trading only.

## Safety and limitations
- Real trading is disabled. No wallet, private key, signing, or transaction submission is used.
- The market score is **not** a token-security audit. Security remains UNVERIFIED.
- Fast polling does not guarantee fast or executable prices. DexScreener data can be delayed, stale, incomplete, or unavailable.
- Stop-loss and take-profit thresholds are observed from sampled prices; they are not guaranteed execution prices. Fast crashes or missing liquidity can cause larger losses.
- The latest token profiles endpoint is a discovery feed, not a complete new-launch feed.
- The default 5-second monitor and 15-second discovery intervals are configurable. API rate limits and network latency can make actual cycles slower.

## Termux
~~~bash
pkg update -y
pkg install python git -y
git clone -b termux-paper-mvp https://github.com/benedick3432/grok-trader.git
cd grok-trader
pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python bot.py
~~~

If the folder already exists, run git pull origin termux-paper-mvp inside it. Stop with Ctrl+C.

## Experimental paper settings
- Discovery interval: 15 seconds
- Open-position monitoring interval: 5 seconds
- Position report interval: 30 seconds
- Minimum liquidity: $15,000
- Minimum 5-minute volume: $10,000
- Minimum 5-minute transactions: 20
- Minimum market score: 70/100
- Maximum open positions: 3
- Paper position size: $25
- Stop-loss threshold: 8% below effective paper entry
- Take-profit threshold: 12% above effective paper entry
- Estimated fee: 0.25%; estimated slippage: 3%
- Daily realized-loss pause: $30
- Re-entry cooldown: 60 minutes

These are experimental paper-test parameters, not profitable settings or financial advice. With estimated 3% slippage on both entry and exit, small gross targets can be consumed by costs. Measure actual paper expectancy, win rate, drawdown, and cost sensitivity before changing parameters.

## Architecture
- A dedicated worker monitors open positions every 5 seconds by default.
- A separate worker discovers new candidates every 15 seconds by default.
- SQLite uses separate worker connections and a busy timeout.
- Existing paper history is retained; the bot does not reset the database.
- Daily loss pause blocks new entries but continues monitoring open positions.
- Position reports include estimated unrealized net PnL; estimates include configured fee and slippage assumptions.
