import os
import time
import sqlite3
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from analysis import analyze_pair

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DB = os.getenv("DATABASE_PATH", "paper_trading.db")
API = "https://api.dexscreener.com"
DISCOVERY_INTERVAL = max(5, int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "15")))
MONITOR_INTERVAL = max(2, int(os.getenv("POSITION_MONITOR_INTERVAL_SECONDS", "5")))
REPORT_INTERVAL = max(10, int(os.getenv("POSITION_REPORT_INTERVAL_SECONDS", "30")))

MIN_LIQ = float(os.getenv("MIN_LIQUIDITY_USD", "15000"))
MAX_AGE = int(os.getenv("MAX_TOKEN_AGE_MINUTES", "1440"))
MIN_VOL = float(os.getenv("MIN_VOLUME_5M_USD", "10000"))
MIN_TXNS = int(os.getenv("MIN_TXNS_5M", "20"))
MIN_SCORE = int(os.getenv("MIN_ANALYSIS_SCORE", "70"))
START_BALANCE = float(os.getenv("PAPER_BALANCE_USD", "1000"))
SIZE = float(os.getenv("TRADE_SIZE_USD", "25"))
MAX_POS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
STOP = float(os.getenv("STOP_LOSS_PCT", "8")) / 100
TAKE = float(os.getenv("TAKE_PROFIT_PCT", "12")) / 100
FEE = float(os.getenv("ESTIMATED_FEE_PCT", "0.25")) / 100
SLIP = float(os.getenv("ESTIMATED_SLIPPAGE_PCT", "3")) / 100
DAILY_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT_USD", "30"))
COOLDOWN = int(os.getenv("REENTRY_COOLDOWN_MINUTES", "60"))

_thread_local = threading.local()
HEADERS = {"User-Agent": "grok-trader-paper-analyst/0.3"}

def http_get(url):
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    response = session.get(url, timeout=10)
    response.raise_for_status()
    return response

def connect_db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c

def db():
    c = connect_db()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL NOT NULL)")
    c.execute("""CREATE TABLE IF NOT EXISTS positions (
        mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, entry REAL,
        amount REAL, opened TEXT, status TEXT, pair_address TEXT)""")
    # Safe migration for databases created by earlier bot versions.
    columns = {row[1] for row in c.execute("PRAGMA table_info(positions)").fetchall()}
    if "pair_address" not in columns:
        c.execute("ALTER TABLE positions ADD COLUMN pair_address TEXT")
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, side TEXT,
        price REAL, amount REAL, pnl REAL, at TEXT, note TEXT)""")
    c.execute("INSERT OR IGNORE INTO state VALUES ('cash', ?)", (START_BALANCE,))
    c.commit()
    return c

def get_pairs(mint):
    pairs = http_get(f"{API}/token-pairs/v1/solana/{mint}").json()
    if not isinstance(pairs, list):
        return []
    return sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)

def latest_profiles():
    data = http_get(f"{API}/token-profiles/latest/v1").json()
    if not isinstance(data, list):
        return []
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

def open_positions(c):
    return c.execute(
        "SELECT mint, symbol, entry, amount, pair_address FROM positions WHERE status='OPEN'"
    ).fetchall()


def fetch_pairs_timed(mint):
    started = time.monotonic()
    pairs = get_pairs(mint)
    return pairs, time.monotonic() - started

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
    invested = (amount * entry) / max(0.000001, (1 - FEE))
    pnl = proceeds - invested
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    now = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE state SET value=? WHERE key='cash'", (cash + proceeds,))
    c.execute("UPDATE positions SET status='CLOSED' WHERE mint=?", (mint,))
    c.execute(
        "INSERT INTO trades(mint,symbol,side,price,amount,pnl,at,note) VALUES(?,?,?,?,?,?,?,?)",
        (mint, symbol, "SELL", price, amount, pnl, now, reason)
    )
    c.commit()
    change = price / entry - 1
    logging.info(
        "PAPER SELL %s | change=%+.1f%% | realized PnL=$%.2f | reason=%s",
        symbol, change * 100, pnl, reason
    )

def monitor_open_positions(c):
    snapshots = []
    rows = open_positions(c)
    if not rows:
        return snapshots

    # Fetch prices concurrently: one slow token request should not block every
    # other open position. Database writes remain on this thread.
    workers = min(8, len(rows))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_pairs_timed, row[0]): row for row in rows}
        for future in as_completed(futures):
            mint, symbol, entry, amount, saved_pair_address = futures[future]
            try:
                pairs, request_seconds = future.result()
                if request_seconds > MONITOR_INTERVAL:
                    logging.warning(
                        "SLOW PRICE REQUEST %s | %.2fs (monitor target %ss)",
                        symbol, request_seconds, MONITOR_INTERVAL
                    )
                if not pairs:
                    logging.warning("OPEN POSITION has no pair data; keeping it open: %s", symbol)
                    continue

                # Keep monitoring the same liquidity pool used at entry.
                # Never silently switch to another pool's price.
                if saved_pair_address:
                    pair = next((p for p in pairs if p.get("pairAddress") == saved_pair_address), None)
                    if pair is None:
                        logging.warning(
                            "SAVED PAIR MISSING for %s | keeping position open; refusing pool switch",
                            symbol
                        )
                        continue
                else:
                    pair = pairs[0]
                    saved_pair_address = pair.get("pairAddress")
                    if saved_pair_address:
                        c.execute(
                            "UPDATE positions SET pair_address=? WHERE mint=? AND status='OPEN'",
                            (saved_pair_address, mint)
                        )
                        c.commit()
                        logging.info("LEGACY POSITION pinned to pair %s | %s",
                                     saved_pair_address[:10], symbol)

                price = float(pair.get("priceUsd") or 0)
                if price <= 0:
                    logging.warning("Invalid price for open position %s; keeping it open", symbol)
                    continue

                change = price / entry - 1
                invested = (amount * entry) / max(0.000001, (1 - FEE))
                estimated_exit = amount * price * (1 - FEE - SLIP)
                estimated_pnl = estimated_exit - invested
                net_pct = (estimated_pnl / invested * 100) if invested else 0.0
                logging.debug(
                    "PRICE CHECK %s | pair=%s | price=$%.10f | move=%+.2f%% | est.net=%+.2f%%",
                    symbol, (saved_pair_address or "unknown")[:10], price, change * 100, net_pct
                )

                if change <= -STOP:
                    close_position(c, mint, pair, "stop-loss threshold observed")
                elif change >= TAKE:
                    close_position(c, mint, pair, "take-profit threshold observed")
                else:
                    snapshots.append((symbol, change * 100, estimated_pnl))
            except Exception as exc:
                logging.warning("Position monitor failed for %s: %s", symbol, exc)
    return snapshots

def consider_buy(c, profile, pair):
    mint = profile["tokenAddress"]
    if c.execute("SELECT 1 FROM positions WHERE mint=? AND status='OPEN'", (mint,)).fetchone():
        return {"status": "already_open"}
    if recently_sold(c, mint):
        return {"status": "cooldown"}
    analysis = analyze_pair(pair, MIN_LIQ, MIN_VOL, MIN_TXNS, MAX_AGE, MIN_SCORE)
    m = analysis["metrics"]
    if not analysis["eligible"]:
        return {"status": "filtered", "analysis": analysis}
    if daily_realized_pnl(c) <= -DAILY_LIMIT:
        return {"status": "daily_limit", "analysis": analysis}
    count = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    if count >= MAX_POS:
        return {"status": "capacity", "analysis": analysis}
    if cash < SIZE or SIZE <= 0:
        return {"status": "cash", "analysis": analysis}
    token = pair.get("baseToken") or {}
    symbol = (token.get("symbol") or "UNKNOWN")[:20]
    name = (token.get("name") or "")[:60]
    price = m["price"]
    effective_price = price * (1 + SLIP)
    amount = (SIZE * (1 - FEE)) / effective_price
    now = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE state SET value=? WHERE key='cash'", (cash - SIZE,))
    pair_address = pair.get("pairAddress")
    c.execute(
        """INSERT INTO positions
           (mint, symbol, name, entry, amount, opened, status, pair_address)
           VALUES(?,?,?,?,?,?,?,?)""",
        (mint, symbol, name, effective_price, amount, now, "OPEN", pair_address)
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
    return {"status": "bought", "analysis": analysis, "symbol": symbol}

def report(c, snapshots=None):
    cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
    positions = open_positions(c)
    realized = float(c.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE side='SELL'"
    ).fetchone()[0])
    daily = daily_realized_pnl(c)
    paused = daily <= -DAILY_LIMIT
    if snapshots is None:
        logging.info(
            "PORTFOLIO | cash=$%.2f | open positions=%d | realized PnL=$%+.2f | daily PnL=$%+.2f | new buys=%s",
            cash, len(positions), realized, daily, "PAUSED" if paused else "ENABLED"
        )
    else:
        unrealized = sum(item[2] for item in snapshots)
        logging.info(
            "PORTFOLIO | cash=$%.2f | open positions=%d | est. unrealized PnL=$%+.2f | realized PnL=$%+.2f | daily PnL=$%+.2f | new buys=%s",
            cash, len(positions), unrealized, realized, daily,
            "PAUSED" if paused else "ENABLED"
        )
        for symbol, change_pct, pnl in snapshots:
            logging.info("OPEN POSITION %s | price change=%+.2f%% | estimated net PnL=$%+.2f", symbol, change_pct, pnl)

def monitor_worker(stop_event):
    c = connect_db()
    last_report = 0.0
    logging.info(
        "POSITION MONITOR started | interval=%ss | stop-loss=%.1f%% | take-profit=%.1f%%",
        MONITOR_INTERVAL, STOP * 100, TAKE * 100
    )
    try:
        while not stop_event.is_set():
            started = time.monotonic()
            snapshots = monitor_open_positions(c)
            if time.monotonic() - last_report >= REPORT_INTERVAL:
                report(c, snapshots)
                last_report = time.monotonic()
            elapsed = time.monotonic() - started
            if elapsed > MONITOR_INTERVAL:
                logging.warning("Position checks took %.1fs (target interval %ss)", elapsed, MONITOR_INTERVAL)
            stop_event.wait(max(0.0, MONITOR_INTERVAL - elapsed))
    finally:
        c.close()

def discovery_worker(stop_event):
    c = connect_db()
    logging.info("TOKEN DISCOVERY started | interval=%ss", DISCOVERY_INTERVAL)
    try:
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                daily = daily_realized_pnl(c)
                count = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
                cash = float(c.execute("SELECT value FROM state WHERE key='cash'").fetchone()[0])
                if daily <= -DAILY_LIMIT:
                    logging.warning("DISCOVERY paused: daily loss limit reached ($%.2f)", daily)
                elif count >= MAX_POS:
                    logging.info("DISCOVERY skipped: position capacity full (%d/%d)", count, MAX_POS)
                elif cash < SIZE:
                    logging.info("DISCOVERY skipped: insufficient paper cash")
                else:
                    profiles = latest_profiles()
                    stats = {
                        "profiles": len(profiles), "pairs": 0, "analyzed": 0,
                        "filtered": 0, "bought": 0, "already_open": 0,
                        "cooldown": 0, "errors": 0, "capacity": 0, "cash": 0,
                        "daily_limit": 0
                    }
                    reasons = {}
                    candidates = []
                    for profile in profiles:
                        if stop_event.is_set():
                            break
                        try:
                            mint = profile["tokenAddress"]
                            if c.execute(
                                "SELECT 1 FROM positions WHERE mint=? AND status='OPEN'", (mint,)
                            ).fetchone():
                                stats["already_open"] += 1
                                continue
                            pair_list = get_pairs(mint)
                            if not pair_list:
                                continue
                            stats["pairs"] += 1
                            pair = pair_list[0]
                            preview = analyze_pair(pair, MIN_LIQ, MIN_VOL, MIN_TXNS, MAX_AGE, MIN_SCORE)
                            stats["analyzed"] += 1
                            token = pair.get("baseToken") or {}
                            candidates.append((
                                preview["score"], (token.get("symbol") or "UNKNOWN")[:20],
                                preview["metrics"]["liquidity"], preview["metrics"]["volume_5m"],
                                preview["metrics"]["txns_5m"], preview["eligible"]
                            ))
                            result = consider_buy(c, profile, pair)
                            status = result["status"]
                            if status == "bought":
                                stats["bought"] += 1
                            elif status == "filtered":
                                stats["filtered"] += 1
                                for reason in result["analysis"]["reasons"]:
                                    reasons[reason] = reasons.get(reason, 0) + 1
                            elif status in stats:
                                stats[status] += 1
                        except Exception as exc:
                            stats["errors"] += 1
                            logging.warning("Token scan skipped: %s", exc)

                    logging.info(
                        "DISCOVERY SUMMARY | profiles=%d | pairs=%d | analyzed=%d | filtered=%d | bought=%d | open=%d | cooldown=%d | errors=%d",
                        stats["profiles"], stats["pairs"], stats["analyzed"],
                        stats["filtered"], stats["bought"], stats["already_open"],
                        stats["cooldown"], stats["errors"]
                    )
                    if reasons:
                        top_reasons = sorted(reasons.items(), key=lambda item: item[1], reverse=True)[:5]
                        logging.info("FILTER REASONS | %s", " | ".join(
                            f"{reason}: {amount}" for reason, amount in top_reasons
                        ))
                    if candidates:
                        top = sorted(candidates, key=lambda item: item[0], reverse=True)[:3]
                        logging.info("TOP CANDIDATES | %s", " | ".join(
                            f"{symbol} score={score} liq={liq:.0f} vol5m={vol:.0f} tx5m={txns} eligible={eligible}"
                            for score, symbol, liq, vol, txns, eligible in top
                        ))
                report(c)
            except Exception as exc:
                logging.error("Discovery scan error: %s", exc)
            elapsed = time.monotonic() - started
            if elapsed > DISCOVERY_INTERVAL:
                logging.warning("Discovery cycle took %.1fs (target interval %ss)", elapsed, DISCOVERY_INTERVAL)
            stop_event.wait(max(0.0, DISCOVERY_INTERVAL - elapsed))
    finally:
        c.close()

def main():
    initial = db()
    initial.close()
    stop_event = threading.Event()
    monitor = threading.Thread(target=monitor_worker, args=(stop_event,), name="position-monitor")
    discovery = threading.Thread(target=discovery_worker, args=(stop_event,), name="token-discovery")
    logging.info("Grok Trader v3 fast-loop Solana paper analyst started. REAL TRADING IS DISABLED.")
    logging.info("Discovery=%ss | position monitoring=%ss | security status remains UNVERIFIED.",
                 DISCOVERY_INTERVAL, MONITOR_INTERVAL)
    monitor.start()
    discovery.start()
    try:
        while monitor.is_alive() and discovery.is_alive():
            monitor.join(timeout=1)
            discovery.join(timeout=1)
    except KeyboardInterrupt:
        logging.info("Stop requested by user.")
        stop_event.set()
    finally:
        stop_event.set()
        monitor.join()
        discovery.join()
        logging.info("Grok Trader stopped. Real trading was never enabled.")

if __name__ == "__main__":
    main()
