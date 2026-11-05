"""Transparent market-quality scoring; not a token-security audit."""
def _num(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default

def pair_metrics(pair):
    import time
    liquidity = _num((pair.get("liquidity") or {}).get("usd"))
    volume = _num((pair.get("volume") or {}).get("m5"))
    txns = (pair.get("txns") or {}).get("m5") or {}
    buys, sells = int(_num(txns.get("buys"))), int(_num(txns.get("sells")))
    created = pair.get("pairCreatedAt")
    age = None if not created else max(0.0, (time.time() * 1000 - _num(created)) / 60000)
    changes = pair.get("priceChange") or {}
    return {
        "liquidity": liquidity, "volume_5m": volume, "txns_5m": buys + sells,
        "buys_5m": buys, "sells_5m": sells, "age_minutes": age,
        "price": _num(pair.get("priceUsd")),
        "change_5m_pct": _num(changes.get("m5"), None),
        "change_1h_pct": _num(changes.get("h1"), None),
    }

def analyze_pair(pair, min_liquidity=15000, min_volume=10000,
                 min_txns=20, max_age=1440, min_score=70):
    m = pair_metrics(pair)
    failures, notes = [], []
    checks = [
        (m["price"] > 0, "Geçerli fiyat yok"),
        (m["liquidity"] >= min_liquidity, "Likidite eşiğinin altında"),
        (m["volume_5m"] >= min_volume, "5 dakikalık hacim düşük"),
        (m["txns_5m"] >= min_txns, "İşlem sayısı düşük"),
        (m["age_minutes"] is not None and m["age_minutes"] <= max_age, "Parite yaşı uygun değil"),
    ]
    failures.extend(message for passed, message in checks if not passed)
    score = 0
    score += 20 if m["liquidity"] >= 50000 else 15 if m["liquidity"] >= 25000 else 10
    score += 20 if m["volume_5m"] >= 50000 else 15 if m["volume_5m"] >= 20000 else 10
    score += 10 if m["txns_5m"] >= 100 else 7 if m["txns_5m"] >= 40 else 4
    ratio = m["buys_5m"] / max(1, m["sells_5m"])
    score += 10 if ratio >= 1.5 else 7 if ratio >= 1 else 2
    m5, h1 = m["change_5m_pct"], m["change_1h_pct"]
    if m5 is not None and h1 is not None:
        score += 20 if -2 <= m5 <= 12 and -5 <= h1 <= 25 else 12 if -5 <= m5 <= 20 and -10 <= h1 <= 40 else 2
    else:
        notes.append("Fiyat momentumu verisi eksik")
    age = m["age_minutes"]
    if age is not None:
        score += 10 if 10 <= age <= 360 else 6 if 5 <= age <= 720 else 2
    turnover = m["volume_5m"] / max(1, m["liquidity"])
    score += 10 if 0.5 <= turnover <= 3 else 6 if 0.15 <= turnover <= 5 else 2
    if m5 is not None and m5 < -5:
        failures.append("Son 5 dakikada sert düşüş")
    if m5 is not None and m5 > 25:
        failures.append("Son 5 dakikada aşırı fiyat sıçraması")
    if score < min_score:
        failures.append("Analiz puanı eşik altında")
    return {
        "score": min(100, score), "eligible": not failures,
        "reasons": notes + failures if notes or failures else ["Piyasa filtrelerini geçti; güvenlik doğrulaması değildir"],
        "metrics": m, "security_status": "UNVERIFIED",
    }
