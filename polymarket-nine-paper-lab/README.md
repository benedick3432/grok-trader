# Polymarket NINE Paper Lab

A manual, Grok-assisted research workflow for short-duration BTC Up/Down markets.

**PAPER ONLY — NO LIVE TRADING.** This repository contains prompts, a settings file, and an audit journal template. It does not connect to wallets, submit orders, call trading APIs, or monitor markets in the background.

## Workflow

SPOTTER → PRIOR → EDGE → KELLY → TAKER → CLOSER

Each role is a separate Grok conversation. The operator manually copies the same timestamped market snapshot and each prior output between chats.

## Included

- `docs/SETUP_GUIDE.md` — setup, formulas, gates, and operating procedure
- `agents/` — six complete role prompts
- `config/settings.json` — frozen illustrative trial settings
- `data/paper_log.csv` — audit journal header row

## Start here

1. Read [the setup guide](docs/SETUP_GUIDE.md).
2. Create six Grok chats and paste the matching prompt from `agents/`.
3. Copy `data/paper_log.csv` into Google Sheets or Excel.
4. Before collecting results, freeze the thresholds in `config/settings.json`.
5. Log every snapshot, including SKIPs and unresolved markets.

## Important

The Reel's displayed "$9.10 FIRST BET" and "$400K+ PNL" are unverified creator/display figures. They are not evidence of realized profit, a starting bankroll, or a reproducible strategy. All thresholds and example values in this lab are illustrative, not validated trading signals.

Educational simulation only; not investment advice. Check the exact market's own rules, settlement source, fees, liquidity, and any geographic restrictions.
