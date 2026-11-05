import os
import time
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv
from analysis import analyze_pair

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
DB = os.getenv("DATABASE_PATH", "paper_trading.db")
API = "https://api.dexscreener.com"
POLL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
MIN_LIQ = float(os.getenv("MIN_LIQUIDITY_USD", "15000"))
MAX_AGE = int(os.getenv("MAX_TOKEN_AGE_MINUTES", "1440"))
MIN_VOL = float(os.getenv("MIN_VOLUME_5M_USD", "10000"))
MIN_TXNS = int(os.getenv("MIN_TXNS_5M", "20"))
MIN_SCORE = int(os.getenv("MIN_ANALYSIS_SCORE", "70"))
START_BALANCE = float(os.getenv("PAPER_BALANCE_USD", "1000"))
SIZE = float(os.getenv("TRADE_SIZE_USD", "25"))
MAX_POS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
STOP = float(os.getenv("STOP_LOSS_PCT", "20")) / 100
TAKE = float(os.getenv("TAKE_PROFIT_PCT", "40")) / 100
FEE = float(os.getenv("ESTIMATED_FEE_PCT", "0.25")) / 100
SLIP = float(os.getenv("ESTIMATED_SLIPPAGE_PCT", "3")) / 100
DAILY_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT_USD", "30"))
COOLDOWN = int(os.getenv("REENTRY_COOLDOWN_MINUTES", "60"))
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "grok-trader-paper-analyst/0.2"})

def db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL NOT NULL)")
    c.execute("""CREATE TABLE IF NOT EXISTS positions (
        mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, entry REAL,
        amount REAL, opened TEXT, status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, side TEXT,
        price REAL, amount REAL, pnl REAL, at TEXT, note TEXT)""")
    c.execute("INSERT OR IGNORE INTO state VALUES ('cash', ?)", (START_BALANCE,))
    c.commit()
    return c

def get_pairs(mint):
    response = SESSION.get(f"{API}/token-pairs/v1/solana/{mint}", timeout=15)
    response.raise_for_status()
    pairs = response.json()
    if not isinstance(pairs, list):
        return []
    return sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)

def latest_profiles():
    response = SESSION.get(f"{API}/token-profiles/latest/v1", timeout=15)
    response.raise_for_status()
    data = response.json()
    return [x for x in data if x.get("chainId") == "solana" and x.get("tokenAddress")]

def daily_realized_pnl(c):
    today = datetime.now(timezone.utc).date().isoformat()
    row = c.execute(
        "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE side='SELL' AND substr(at,1,10)=?",
        (today,)
    ).fetchone()
    return float(row[0] or 0)

def recently_sold(c, mint):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN)).isoformat()
    row = c.execute(
        "SELECT 1 FROM trades WHERE mint=? AND side='SELL' AND at>=? LIMIT 1",
        (mint, cutoff)
    ).fetchone()
    return row is not None

def open_position_mints(c):
    return [r[0] for r in c.execute("SELECT mint FROM positions WHERE status='OPEN'").fetchall()]

def close_position(c, mint, pair, reason):
    row = c.execute(
        "SELECT symbol, entry, amount FROM positions WHERE mint=? AND status='OPEN'",
        (mint,)
    ).fetchone()
    if not row:
        return
    symbol, entry, amount = row
    price = float(pair.get("priceUsd") or 0)
    if price <= 0:
        logging.warning("Cannot close %s: invalid price", symbol)
        return
    proceeds = amount * price * (1 - FEE - SLIP)
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    invested = (amount * entry) / max(0.000001, (1 - FEE))
    pnl = proceeds - invested
    now = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE state SET value=? WHERE key='cash'", (cash + proceeds,))
    c.execute("UPDATE positions SET status='CLOSED' WHERE mint=?", (mint,))
    c.execute(
        "INSERT INTO trades(mint,symbol,side,price,amount,pnl,at,note) VALUES(?,?,?,?,?,?,?,?)",
        (mint, symbol, "SELL", price, amount, pnl, now, reason)
    )
    c.commit()
    change = price / entry - 1
    logging.info("PAPER SELL %s | change=%+.1f%% | realized PnL=$%.2f | reason=%s",
                 symbol, change * 100, pnl, reason)

def monitor_open_positions(c):
    # Monitor positions independently of the discovery feed, so delisted profiles
    # do not silently stop being checked.
    for mint in open_position_mints(c):
        try:
            pairs = get_pairs(mint)
            if not pairs:
                logging.warning("OPEN POSITION has no pair data; keeping it open: %s", mint)
                continue
            pair = pairs[0]
            row = c.execute(
                "SELECT entry, symbol FROM positions WHERE mint=? AND status='OPEN'",
                (mint,)
            ).fetchone()
            if not row:
                continue
            entry, symbol = row
            price = float(pair.get("priceUsd") or 0)
            if price <= 0:
                logging.warning("Invalid price for open position %s; keeping it open", symbol)
                continue
            change = price / entry - 1
            if change <= -STOP:
                close_position(c, mint, pair, "stop-loss threshold observed")
            elif change >= TAKE:
                close_position(c, mint, pair, "take-profit threshold observed")
        except Exception as exc:
            logging.warning("Position monitor failed for %s: %s", mint, exc)

def consider_buy(c, profile, pair):
    mint = profile["tokenAddress"]
    if c.execute("SELECT 1 FROM positions WHERE mint=? AND status='OPEN'", (mint,)).fetchone():
        return
    if recently_sold(c, mint):
        return
    analysis = analyze_pair(pair, MIN_LIQ, MIN_VOL, MIN_TXNS, MAX_AGE, MIN_SCORE)
    m = analysis["metrics"]
    if not analysis["eligible"]:
        return
    if daily_realized_pnl(c) <= -DAILY_LIMIT:
        return
    open_count = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    if open_count >= MAX_POS or cash < SIZE or SIZE <= 0:
        return
    token = pair.get("baseToken") or {}
    symbol = (token.get("symbol") or "UNKNOWN")[:20]
    name = (token.get("name") or "")[:60]
    price = m["price"]
    # Simulated costs only; this is not an executable quote.
    effective_price = price * (1 + SLIP)
    amount = (SIZE * (1 - FEE)) / effective_price
    now = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE state SET value=? WHERE key='cash'", (cash - SIZE,))
    c.execute(
        "INSERT INTO positions VALUES(?,?,?,?,?,?,?)",
        (mint, symbol, name, effective_price, amount, now, "OPEN")
    )
    c.execute(
        "INSERT INTO trades(mint,symbol,side,price,amount,pnl,at,note) VALUES(?,?,?,?,?,?,?,?)",
        (mint, symbol, "BUY", effective_price, amount, 0, now,
         f"paper entry; market score={analysis['score']}; security unverified")
    )
    c.commit()
    logging.info(
        "PAPER BUY %s | score=%d/100 | liq=$%.0f | vol5m=$%.0f | tx5m=%d | age=%.1fm | SECURITY=UNVERIFIED",
        symbol, analysis["score"], m["liquidity"], m["volume_5m"],
        m["txns_5m"], m["age_minutes"]
    )

def report(c):
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    opened = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    realized = float(c.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE side='SELL'").fetchone()[0])
    daily = daily_realized_pnl(c)
    paused = daily <= -DAILY_LIMIT
    logging.info(
        "PORTFOLIO | cash=$%.2f | open positions=%d | realized PnL=$%.2f | daily PnL=$%.2f | new buys=%s",
        cash, opened, realized, daily, "PAUSED" if paused else "ENABLED"
    )

def main():
    c = db()
    logging.info("Grok Trader v2 Solana Paper Analyst started. REAL TRADING IS DISABLED.")
    logging.info("Market score is not a security audit; token security status remains UNVERIFIED.")
    while True:
        try:
            monitor_open_positions(c)
            profiles = latest_profiles()
            logging.info("Solana profiles received: %d", len(profiles))
            for profile in profiles:
                try:
                    mint = profile["tokenAddress"]
                    if c.execute("SELECT 1 FROM positions WHERE mint=? AND status='OPEN'", (mint,)).fetchone():
                        continue
                    pairs = get_pairs(mint)
                    if pairs:
                        consider_buy(c, profile, pairs[0])
                except Exception as exc:
                    logging.warning("Token scan skipped: %s", exc)
            report(c)
        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            break
        except Exception as exc:
            logging.error("Scan error: %s", exc)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
