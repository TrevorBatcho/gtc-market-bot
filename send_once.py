# send_once.py  — GTC Market Bot (daily + alerts)
# ------------------------------------------------
# Env needed:
#  TELEGRAM_TOKEN   -> Bot token (from BotFather)
#  CHANNEL_ID       -> Telegram channel/chat id (e.g., -1001234567890)
#  ALPHA_VANTAGE_KEY-> Alpha Vantage API key
#  NEWS_API_KEY     -> (optional) NewsAPI.org key
#  RUN_MODE         -> "daily" or "alert"  (default = "alert")

import os
import time
import datetime as dt
import requests
from typing import List, Tuple, Optional

# ========= EDITABLE CONFIG =========
PAIRS: List[Tuple[str, str]] = [
    ("EUR", "USD"),
    ("GBP", "USD"),
    ("USD", "JPY"),
    ("XAU", "USD"),   # Gold priced in USD (Alpha Vantage supports this)
    # ("USD","LKR"),
]

# Alerts mode: send only if abs(% move) >= threshold from prior hour bar
ALERT_THRESHOLD_PCT: float = 0.5  # e.g. 0.5%  -> send only if move >= 0.5%

# News (used in daily mode). Set HEADLINES_LIMIT=0 to disable quickly.
HEADLINES_QUERY: str = "forex OR eurusd OR gbpusd OR usdjpy OR gold"
HEADLINES_SOURCES: List[str] = ["bloomberg.com", "reuters.com", "wsj.com", "ft.com"]
HEADLINES_LIMIT: int = 3
# ===================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
NEWS_KEY = os.getenv("NEWS_API_KEY")  # optional

if not TOKEN or not CHAT_ID or not API_KEY:
    raise SystemExit("Missing TELEGRAM_TOKEN, CHANNEL_ID or ALPHA_VANTAGE_KEY")

TG_API = f"https://api.telegram.org/bot{TOKEN}"
AV_BASE = "https://www.alphavantage.co/query"

def _ts_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def send_message(text: str, disable_web_page_preview: bool = True) -> None:
    url = f"{TG_API}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_web_page_preview,
    }
    r = requests.post(url, data=payload, timeout=20)
    if not r.ok:
        print("Telegram send failed:", r.text)
        raise SystemExit(1)

def fetch_fx_spot(from_cur: str, to_cur: str) -> Optional[float]:
    """Realtime spot via CURRENCY_EXCHANGE_RATE. Returns float or None."""
    params = {
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_cur,
        "to_currency": to_cur,
        "apikey": API_KEY,
    }
    try:
        r = requests.get(AV_BASE, params=params, timeout=20)
        j = r.json()
        d = j.get("Realtime Currency Exchange Rate", {})
        rate_str = d.get("5. Exchange Rate")
        return float(rate_str) if rate_str else None
    except Exception as e:
        print("fetch_fx_spot error", from_cur, to_cur, e)
        return None

def fetch_fx_change(from_cur: str, to_cur: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (spot, pct_change) using intraday 60m bars:
      pct_change = (last_close / prev_close - 1) * 100
    Falls back to spot only if intraday unavailable.
    """
    # First, try intraday 60min
    params = {
        "function": "FX_INTRADAY",
        "from_symbol": from_cur,
        "to_symbol": to_cur,
        "interval": "60min",
        "outputsize": "compact",
        "apikey": API_KEY,
    }
    try:
        r = requests.get(AV_BASE, params=params, timeout=20)
        j = r.json()
        series = j.get("Time Series FX (60min)")
        if isinstance(series, dict) and len(series) >= 2:
            # Sort timestamps desc, pick latest two closes
            keys = sorted(series.keys(), reverse=True)
            last = float(series[keys[0]]["4. close"])
            prev = float(series[keys[1]]["4. close"])
            pct = ((last / prev) - 1.0) * 100.0
            return last, pct
    except Exception as e:
        print("fetch_fx_change intraday error", from_cur, to_cur, e)

    # Fallback: get realtime spot only (no change)
    spot = fetch_fx_spot(from_cur, to_cur)
    return spot, None

def fmt_pair(from_cur: str, to_cur: str) -> str:
    return f"{from_cur}/{to_cur}"

def build_daily_text() -> str:
    header = f"📊 <b>GTC Academy — Daily Market Snapshot</b>\n{_ts_utc()}\n\n"
    lines = []
    for a, b in PAIRS:
        spot = fetch_fx_spot(a, b)
        if spot is None:
            lines.append(f"• {fmt_pair(a,b)}: n/a")
        else:
            # format with sensible decimals
            if b in ("JPY"):  # JPY quotes often ~3 decimals
                lines.append(f"• {fmt_pair(a,b)}: {spot:.3f}")
            else:
                lines.append(f"• {fmt_pair(a,b)}: {spot:.5f}")

        # Respect Alpha Vantage rate limit (5 req/min on free tier)
        time.sleep(12)

    text = header + "\n".join(lines)

    # Optional headlines
    if NEWS_KEY and HEADLINES_LIMIT > 0:
        heads = fetch_headlines(HEADLINES_QUERY, HEADLINES_SOURCES, HEADLINES_LIMIT)
        if heads:
            text += "\n\n🗞 <b>Top Headlines</b>\n"
            for title, source in heads:
                text += f"• {title} <i>({source})</i>\n"

    return text

def fetch_headlines(query: str, sources: List[str], limit: int) -> List[Tuple[str, str]]:
    """
    Simple NewsAPI.org query. Returns list of (title, source) — no links printed.
    """
    try:
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit,
            "apiKey": NEWS_KEY,
        }
        if sources:
            params["domains"] = ",".join(sources)
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=20)
        j = r.json()
        arts = j.get("articles", [])[:limit]
        out = []
        for a in arts:
            title = a.get("title") or "Headline"
            source = (a.get("source") or {}).get("name") or "News"
            out.append((title, source))
        return out
    except Exception as e:
        print("fetch_headlines error:", e)
        return []

def build_alert_text(threshold_pct: float) -> Optional[str]:
    """
    Build an alert only for pairs with |% change| >= threshold_pct using intraday 60m bars.
    If none qualify, return None (so the workflow doesn't spam).
    """
    header = f"🔔 <b>GTC Market Alert</b>\n{_ts_utc()}\n\n"
    chosen = []
    for a, b in PAIRS:
        spot, pct = fetch_fx_change(a, b)

        # Respect Alpha Vantage throughput
        time.sleep(12)

        # Skip if we couldn't fetch anything
        if spot is None:
            continue

        move_str = ""
        if pct is not None:
            sign = "▲" if pct >= 0 else "▼"
            move_str = f" ({sign}{abs(pct):.2f}%)"
            if abs(pct) < threshold_pct:
                continue  # do not alert if under threshold
        # else: intraday change unavailable — skip from alerts to avoid noise
        else:
            continue

        if b in ("JPY"):
            chosen.append(f"• {fmt_pair(a,b)}: {spot:.3f}{move_str}")
        else:
            chosen.append(f"• {fmt_pair(a,b)}: {spot:.5f}{move_str}")

    if not chosen:
        return None
    return header + "\n".join(chosen)

def main(mode: str = "alert") -> None:
    mode = (mode or "alert").lower()
    if mode == "daily":
        text = build_daily_text()
        send_message(text)
        print("Daily sent.")
    else:
        text = build_alert_text(ALERT_THRESHOLD_PCT)
        if text:
            send_message(text)
            print("Alert sent.")
        else:
            print("No pairs exceeded threshold; no alert sent.")

if __name__ == "__main__":
    main(os.getenv("RUN_MODE", "alert"))
