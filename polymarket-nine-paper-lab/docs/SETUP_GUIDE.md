# NINE / ROC + Volatility Paper Lab — Setup Guide

**PAPER LAB • NO LIVE TRADING**

This is an original manual learning workflow based on the supplied guide. It is not a reconstruction of any creator's private bot, model, code, or trade history.

## 1. What the displayed figures mean

The Reel displays "FIRST BET: $9.10" and "PNL: $400K+". Treat these as creator/displayed figures, not independently verified realized profits. A first bet does not establish starting bankroll, and the display does not prove that one $9.10 position compounded into $400K.

The thresholds below are illustrative trial settings, not validated trading rules.

## 2. What you need

- Grok at https://grok.com — six separate saved chats.
- A specific BTC Up/Down event on https://polymarket.com.
- The exact event URL, title, start/end time, timezone, written Rules, and resolution source.
- Timestamped BTC observations from one named source.
- The selected outcome's observed bid, ask, spread, quote time, and displayed depth.
- Google Sheets or Excel, screenshots, and a $1,000 virtual account.

No wallet, API key, trading terminal, real order, or real funds are used.

## 3. Six-role workflow

SPOTTER → PRIOR → EDGE → KELLY → TAKER → CLOSER.

Each role is a separate Grok chat. YOU manually pass the same timestamped snapshot and previous outputs between chats. These are not autonomous bots.

1. **SPOTTER** calculates three-minute ROC.
2. **PRIOR** requires defensible probability evidence; otherwise q = NOT ESTIMABLE.
3. **EDGE** checks five-minute range, spread, depth, quote freshness, and costs.
4. **KELLY** applies the virtual 1% risk cap.
5. **TAKER** writes a hypothetical ticket or NO PAPER TRADE.
6. **CLOSER** checks official settlement and journals the result.

Paste the matching complete prompt from the `agents/` folder into each chat.

## 4. Select one exact market

1. Open one specific BTC Up/Down event.
2. Save its full URL, title, outcome, event window, and timezone.
3. Open the event's Rules and identify the exact settlement reference and resolution source. Do not assume the spot exchange chart is the settlement source.
4. Record observed bid, ask, spread, quote timestamp, and visible depth.
5. Capture a timestamped screenshot before resolution. If the quote was not captured in time, do not backfill an entry.

Short-duration contracts can change faster than a six-chat manual workflow. Use captured snapshots for paper research, not as a live execution process.

## 5. Calculate ROC first, volatility second

Collect at least six BTC observations one minute apart (t−5 through t) from ONE named price source, recording UTC times. Use the highest and lowest sampled prices for RANGE5 and the reading at t−3 for ROC3. This is a research proxy; the contract settles under its own written rules.

### Formulas

`ROC3 (%) = 100 × (BTC_now / BTC_3_minutes_ago − 1)`

`RANGE5 (%) = 100 × (highest sampled BTC − lowest sampled BTC) / BTC_now`

`SPREAD = observed ask − observed bid`

Illustrative arithmetic: BTC three minutes ago = $70,000; now = $70,084; ROC3 = +0.12%. Five-minute high = $70,100 and low = $69,970; RANGE5 ≈ 0.19%. Ask = $0.59 and bid = $0.57; spread = $0.02.

### Freeze these illustrative gates before testing

- ROC: Up candidate at ROC3 >= +0.10%; Down candidate at ROC3 <= −0.10%; otherwise SKIP.
- Volatility: require RANGE5 <= 0.45%; otherwise SKIP.
- Liquidity/cost: require spread <= $0.03, visible ask/depth sufficient for the hypothetical stake, and a fresh quote; otherwise SKIP.
- If a required input is missing, BLOCK or SKIP. Never ask an AI to fill unknown prices.

These are trial settings, not verified rules from the Reel and not evidence of forecast accuracy. Do not tune them after seeing outcomes.

## 6. Journal

Copy `data/paper_log.csv` into Google Sheets or Excel. One row equals one market snapshot, including blocked setups and SKIPs.

Recommended formulas for row 2 (assuming the CSV columns remain in the documented order):

- I2 (ROC3 %): `=IFERROR((F2/E2-1)*100,"")`
- J2 (RANGE5 %): `=IFERROR((G2-H2)/F2*100,"")`
- M2 (Spread): `=IFERROR(K2-L2,"")`
- W2 (Paper P&L): `=IF(OR(T2="",K2="",V2="",U2=""),"",T2/K2*V2-T2-U2)`

Enter 1 in column V if the selected outcome won and 0 if it lost, based on official resolution. Column U contains modeled costs; enter 0 only if costs are genuinely modeled as zero. Leave unresolved markets OPEN rather than assigning a result.

## 7. Virtual $9.10 arithmetic example

With a $1,000 virtual balance, the 1% cap is $10. A proposed $9.10 paper stake is within that cap, before additional modeled costs. At an observed ask of $0.59, the hypothetical share count is approximately 15.42.

If correct and settled at $1 per share, gross value is about $15.42 and gross gain is about $6.32 before costs. If incorrect, the full $9.10 stake is lost before costs. This is arithmetic, not a documented trade or expected return.

## 8. Run one round

1. Capture one event and snapshot before resolution; send it to SPOTTER.
2. Pass SPOTTER's output to PRIOR, then EDGE.
3. If any gate blocks or q is NOT ESTIMABLE, record SHADOW / NO TRADE. You may still log the later outcome to evaluate the filter, but do not invent a placed bet.
4. Only a fully approved experimental paper decision goes to KELLY and TAKER.
5. Verify official resolution and send the record to CLOSER.

### Handoff card

```text
SNAPSHOT ID: [unique ID]    UTC TIME: [timestamp]
MARKET URL / TITLE / WINDOW: [exact link + start/end]
OUTCOME EVALUATED: [Up / Down]    RULES SOURCE: [link]
BTC SOURCE + 3m AGO / NOW: [source; values]
5m HIGH / LOW: [values from SAME source]
ASK / BID / DEPTH / QUOTE TIME: [observed values]
ROC3 / RANGE5 / SPREAD: [calculated or UNKNOWN]
PRIOR q + EVIDENCE: [or NOT ESTIMABLE]
VIRTUAL BALANCE / PROPOSED PAPER STAKE: [amounts]
OFFICIAL RESOLUTION + LINK: [fill AFTER event]
```

## 9. Test and troubleshoot

- Collect at least 30–50 consecutive snapshots, including SKIPs; freeze thresholds before the first observation.
- Separate observations used to choose thresholds from later out-of-sample checks.
- Measure pass rate, settled outcome frequency, hypothetical net P&L after modeled fees, and missing-data rate.
- If Grok cannot see live markets, paste timestamped observations and source links; never allow invented prices.
- If chart direction conflicts with settlement, read the exact event Rules and reference data.
- If spread, fees, or depth are missing, SKIP; do not assume a mid-price fill or zero fees.
- If six chats take too long, analyze archived snapshots. This is a manual research/replay workflow, not a high-speed autonomous system.

## 10. Reference links

- Polymarket Gamma API docs: https://gamma-api.polymarket.com/docs
- Polymarket CLOB: https://clob.polymarket.com
- Example BTC 5-minute event: https://polymarket.com/event/btc-updown-5m-1788651900

Verify the selected event's current rules, prices, fees, liquidity, settlement reference, and geographic restrictions independently.

**Educational simulation only — not investment advice. No live trading, no wallet access, no order execution, and no background monitoring.**
