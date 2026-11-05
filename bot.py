import os, time, sqlite3, logging
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
DB = "paper_trading.db"
API = "https://api.dexscreener.com"
POLL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
MIN_LIQ = float(os.getenv("MIN_LIQUIDITY_USD", "5000"))
MAX_AGE = int(os.getenv("MAX_TOKEN_AGE_MINUTES", "1440"))
MIN_VOL = float(os.getenv("MIN_VOLUME_5M_USD", "1000"))
MIN_TXNS = int(os.getenv("MIN_TXNS_5M", "10"))
START_BALANCE = float(os.getenv("PAPER_BALANCE_USD", "1000"))
SIZE = float(os.getenv("TRADE_SIZE_USD", "25"))
MAX_POS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
STOP = float(os.getenv("STOP_LOSS_PCT", "20")) / 100
TAKE = float(os.getenv("TAKE_PROFIT_PCT", "40")) / 100
FEE = float(os.getenv("ESTIMATED_FEE_PCT", "0.25")) / 100
SLIP = float(os.getenv("ESTIMATED_SLIPPAGE_PCT", "3")) / 100
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "grok-trader-paper-mvp/0.1"})

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS positions (mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, entry REAL, amount REAL, opened TEXT, status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, side TEXT, price REAL, amount REAL, pnl REAL, at TEXT, note TEXT)""")
    c.execute("INSERT OR IGNORE INTO state VALUES ('cash', ?)", (START_BALANCE,))
    c.commit()
    return c

def get_pairs(mint):
    r = SESSION.get(f"{API}/token-pairs/v1/solana/{mint}", timeout=15)
    r.raise_for_status()
    pairs = r.json()
    if not isinstance(pairs, list): return []
    return sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)

def latest_profiles():
    r = SESSION.get(f"{API}/token-profiles/latest/v1", timeout=15)
    r.raise_for_status()
    data = r.json()
    return [x for x in data if x.get("chainId") == "solana" and x.get("tokenAddress")]

def metrics(pair):
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    vol = (pair.get("volume") or {}).get("m5") or 0
    tx = pair.get("txns") or {}
    t5 = tx.get("m5") or {}
    count = (t5.get("buys") or 0) + (t5.get("sells") or 0)
    created = pair.get("pairCreatedAt")
    age = None if not created else max(0, (time.time() * 1000 - created) / 60000)
    price = float(pair.get("priceUsd") or 0)
    return liq, vol, count, age, price

def paper_cycle(c, profile, pair):
    mint = profile["tokenAddress"]
    token = pair.get("baseToken") or {}
    symbol = (token.get("symbol") or "UNKNOWN")[:20]
    name = (token.get("name") or "")[:60]
    liq, vol, tx_count, age, price = metrics(pair)
    if price <= 0: return
    now = datetime.now(timezone.utc).isoformat()
    row = c.execute("SELECT entry, amount FROM positions WHERE mint=? AND status='OPEN'", (mint,)).fetchone()
    if row:
        entry, amount = row
        change = price / entry - 1
        if change <= -STOP or change >= TAKE:
            proceeds = amount * price * (1 - FEE - SLIP)
            cash = c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0]
            invested = (amount * entry) / (1 - FEE)
            pnl = proceeds - invested
            c.execute("UPDATE state SET value=? WHERE key='cash'", (cash + proceeds,))
            c.execute("UPDATE positions SET status='CLOSED' WHERE mint=?", (mint,))
            c.execute("INSERT INTO trades(mint,symbol,side,price,amount,pnl,at,note) VALUES(?,?,?,?,?,?,?,?)",
                      (mint,symbol,"SELL",price,amount,pnl,now,"paper stop/take"))
            c.commit()
            logging.info("PAPER SELL %s | change=%+.1f%% | realized PnL=$%.2f", symbol, change*100, pnl)
        return
    if age is None or age > MAX_AGE or liq < MIN_LIQ or vol < MIN_VOL or tx_count < MIN_TXNS:
        return
    open_count = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    cash = c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0]
    if open_count >= MAX_POS or cash < SIZE or SIZE <= 0: return
    # Conservative estimated entry cost; this is a simulation, not an executable quote.
    effective_price = price * (1 + SLIP)
    amount = (SIZE * (1 - FEE)) / effective_price
    c.execute("UPDATE state SET value=? WHERE key='cash'", (cash - SIZE,))
    c.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?,?)",
              (mint,symbol,name,effective_price,amount,now,"OPEN"))
    c.execute("INSERT INTO trades(mint,symbol,side,price,amount,pnl,at,note) VALUES(?,?,?,?,?,?,?,?)",
              (mint,symbol,"BUY",effective_price,amount,0,now,"paper entry; estimated slippage/fee"))
    c.commit()
    logging.info("PAPER BUY %s | liq=$%.0f | vol5m=$%.0f | age=%.1fm", symbol,liq,vol,age)

def report(c):
    cash = c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0]
    opened = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    realized = c.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE side='SELL'").fetchone()[0]
    logging.info("PORTFOLIO | cash=$%.2f | open positions=%d | realized PnL=$%.2f",cash,opened,realized)

def main():
    c = db()
    logging.info("Grok Trader paper MVP started. REAL TRADING IS DISABLED.")
    logging.info("DEX Screener latest profiles are discovery signals, not a complete new-launch feed.")
    while True:
        try:
            profiles = latest_profiles()
            logging.info("Profiles received: %d",len(profiles))
            for p in profiles:
                try:
                    pairs = get_pairs(p["tokenAddress"])
                    if pairs: paper_cycle(c,p,pairs[0])
                except Exception as e:
                    logging.warning("Token scan skipped: %s",e)
            report(c)
        except KeyboardInterrupt:
            logging.info("Stopped by user."); break
        except Exception as e:
            logging.error("Scan error: %s",e)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
