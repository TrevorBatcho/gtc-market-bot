# send_once.py  — upgraded (pairs + % alerts + optional news)
import os, time, requests, datetime

TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHANNEL_ID")         # e.g., -1001234567890
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
NEWS_KEY = os.getenv("NEWS_API_KEY")      # optional (add in GitHub Secrets if you want headlines)
RUN_MODE = os.getenv("RUN_MODE", "alert") # "alert" or "daily"
THRESHOLD = float(os.getenv("MOVETHRESH_PCT", "0.5"))  # % move to trigger alert

# === Customize your pairs here ===
# Use 3-letter codes (FX / metals like XAU). All priced vs USD.
WATCHLIST = [
    ("EUR","USD"),
    ("GBP","USD"),
    ("USD","JPY"),
    ("XAU","USD"),  # Gold
    # ("BTC","USD"),  # If you want crypto alerts, comment in & see note below
]

# ---------- Helpers ----------
def send_message_html(text: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, data=payload, timeout=30)
    ok = r.ok
    if not ok:
        print("Send failed:", r.text)
    return ok

def fx_spot(from_cur, to_cur="USD"):
    """Realtime FX spot (or metals like XAU)"""
    url = ( "https://www.alphavantage.co/query"
            f"?function=CURRENCY_EXCHANGE_RATE&from_currency={from_cur}&to_currency={to_cur}&apikey={API_KEY}")
    j = requests.get(url, timeout=30).json()
    try:
        return float(j["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    except Exception:
        return None

def fx_intraday_latest_and_past(from_cur, to_cur="USD", minutes_back=60):
    """
    Intraday 5-min series (FX only).
    Returns (latest_price, price_~minutes_back) if possible.
    """
    url = ( "https://www.alphavantage.co/query"
            f"?function=FX_INTRADAY&from_symbol={from_cur}&to_symbol={to_cur}"
            f"&interval=5min&outputsize=compact&apikey={API_KEY}")
    j = requests.get(url, timeout=30).json()
    series = j.get("Time Series FX (5min)") or {}
    if not series:
        return None, None
    # Sort newest → oldest
    times = sorted(series.keys(), reverse=True)
    latest_time = times[0]
    latest = float(series[latest_time]["4. close"])
    # approx index for 60 min back = 12 bars (5-min * 12)
    idx = min(len(times)-1, 12)
    past = float(series[times[idx]]["4. close"])
    return latest, past

def pct_change(new, old):
    return (new - old) / old * 100.0 if (new is not None and old) else None

def fmt(from_cur, to_cur, p):
    # Show more decimals for JPY; 4 dp for others
    if to_cur in ("JPY",):
        return f"{from_cur}/{to_cur}: {p:,.3f}"
    return f"{from_cur}/{to_cur}: {p:,.4f}"

def get_headlines(n=3):
    """Optional: top 3 finance headlines (needs NEWS_API_KEY secret)."""
    if not NEWS_KEY:
        return []
    try:
        # Simple query; adjust language/country if you want
        url = ("https://newsapi.org/v2/top-headlines?"
               "category=business&language=en&pageSize=3")
        r = requests.get(url, headers={"X-Api-Key": NEWS_KEY}, timeout=30).json()
        arts = r.get("articles") or []
        out = []
        for a in arts[:n]:
            title = a.get("title") or ""
            src = a.get("source",{}).get("name","")
            out.append(f"• {title} <i>({src})</i>")
        return out
    except Exception as e:
        print("News fetch error:", e)
        return []

# ---------- Main modes ----------
def run_daily():
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"📊 <b>GTC Academy — Daily Market Snapshot</b>\n{ts}\n\n"
    lines = []
    for (a,b) in WATCHLIST:
        p = fx_spot(a,b)
        if p is None:
            lines.append(f"• {a}/{b}: n/a")
        else:
            lines.append(f"• {fmt(a,b,p)}")
        time.sleep(15)  # Alpha Vantage free limit: be gentle
    # optional headlines
    headlines = get_headlines(3)
    if headlines:
        lines.append("\n📰 <b>Top Headlines</b>")
        lines.extend(headlines)
    text = header + "\n".join(lines)
    ok = send_message_html(text)
    if ok:
        print("Daily sent OK")

def run_alert():
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"🔔 <b>GTC Market Alert</b>\n{ts}\n"
    alerts = []
    for (a,b) in WATCHLIST:
        latest, past = fx_intraday_latest_and_past(a,b, minutes_back=60)
        if latest is None or past is None:
            print(f"{a}/{b}: intraday data n/a")
        else:
            move = pct_change(latest, past)
            if move is not None and abs(move) >= THRESHOLD:
                arrow = "🔺" if move > 0 else "🔻"
                alerts.append(f"{arrow} {fmt(a,b,latest)}  ({move:.2f}% in ~1h)")
        time.sleep(15)  # rate limit protection
    if alerts:
        text = header + "\n".join(alerts)
        ok = send_message_html(text)
        if ok:
            print("Alert(s) sent OK")
    else:
        print("No alerts ≥ threshold this run.")

if __name__ == "__main__":
    if not (TOKEN and CHAT_ID and API_KEY):
        raise SystemExit("Missing TELEGRAM_TOKEN / CHANNEL_ID / ALPHA_VANTAGE_KEY")
    if RUN_MODE == "daily":
        run_daily()
    else:
        run_alert()
