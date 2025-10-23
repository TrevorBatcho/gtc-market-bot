# send_once.py — GTC Market Bot (daily • alerts • weekly • charts)

import os, time, io
import datetime as dt
from typing import Optional, Dict, List, Tuple
import requests
import matplotlib.pyplot as plt

# -----------------------
# ENV (provided as Secrets in Actions)
# -----------------------
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
NEWS_KEY = os.getenv("NEWS_API_KEY", "")
RUN_MODE = os.getenv("RUN_MODE", "alert")  # alert | daily | weekly | chart
ALERT_THRESHOLD_PCT = float(os.getenv("ALERT_THRESHOLD_PCT", "0.5"))

if not (TOKEN and CHAT_ID and API_KEY):
    raise SystemExit("Missing TELEGRAM_TOKEN / CHANNEL_ID / ALPHA_VANTAGE_KEY")

# ------------- Telegram helpers -------------
TG_BASE = f"https://api.telegram.org/bot{TOKEN}"

def tg_send_message(text: str, disable_web_page_preview: bool=True) -> None:
    url = f"{TG_BASE}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview}
    r = requests.post(url, data=data, timeout=30)
    if not r.ok:
        print("Telegram sendMessage failed:", r.text)

def tg_send_photo(caption: str, png_bytes: bytes) -> None:
    url = f"{TG_BASE}/sendPhoto"
    files = {"photo": ("chart.png", png_bytes)}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    r = requests.post(url, data=data, files=files, timeout=60)
    if not r.ok:
        print("Telegram sendPhoto failed:", r.text)

def now_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

# ------------- AlphaVantage helpers -------------
AV = "https://www.alphavantage.co/query"

def av_get_json(params: Dict) -> Dict:
    params = {**params, "apikey": API_KEY}
    r = requests.get(AV, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fx_realtime(from_cur: str, to_cur: str) -> Optional[float]:
    try:
        j = av_get_json({
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_cur, "to_currency": to_cur
        })
        rate = float(j["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        return rate
    except Exception as e:
        print("fx_realtime err:", e)
        return None

def fx_daily_series(from_cur: str, to_cur: str) -> List[Tuple[str,float]]:
    """Return daily close list [(date, close_float)] descending by date."""
    try:
        j = av_get_json({
            "function": "FX_DAILY",
            "from_symbol": from_cur, "to_symbol": to_cur, "outputsize": "compact"
        })
        series = j["Time Series FX (Daily)"]
        out = [(d, float(v["4. close"])) for d, v in series.items()]
        out.sort(reverse=True)  # newest first
        return out
    except Exception as e:
        print("fx_daily_series err:", e)
        return []

def crypto_daily(symbol: str = "BTC", market: str = "USD") -> List[Tuple[str,float]]:
    try:
        j = av_get_json({
            "function": "DIGITAL_CURRENCY_DAILY",
            "symbol": symbol, "market": market
        })
        series = j["Time Series (Digital Currency Daily)"]
        out = [(d, float(v["4a. close (USD)"])) for d, v in series.items()]
        out.sort(reverse=True)
        return out
    except Exception as e:
        print("crypto_daily err:", e)
        return []

def equity_daily(symbol: str = "SPY") -> List[Tuple[str,float]]:
    """Use SPY ETF as S&P500 proxy."""
    try:
        j = av_get_json({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol, "outputsize": "compact"
        })
        series = j["Time Series (Daily)"]
        out = [(d, float(v["4. close"])) for d, v in series.items()]
        out.sort(reverse=True)
        return out
    except Exception as e:
        print("equity_daily err:", e)
        return []

# ------------- News (optional) -------------
def top_headlines(limit: int = 3) -> List[Tuple[str,str]]:
    """Return [(title, source)] using NewsAPI if key provided; otherwise []"""
    if not NEWS_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/top-headlines"
        params = {"category": "business", "language": "en", "pageSize": limit, "apiKey": NEWS_KEY}
        r = requests.get(url, params=params, timeout=30).json()
        out = []
        for a in r.get("articles", [])[:limit]:
            title = a.get("title","").strip()
            source = (a.get("source") or {}).get("name","")
            if title:
                out.append((title, source))
        return out
    except Exception as e:
        print("news err:", e)
        return []

# ------------- Formatting helpers -------------
def pct_change(new: float, old: float) -> float:
    return (new - old) / old * 100.0

def fmt_pair_line(name: str, latest: Optional[float]) -> str:
    return f"• {name}: {latest:.4f}" if latest is not None else f"• {name}: n/a"

# ------------- Modes -------------
def run_daily():
    eur = fx_realtime("EUR","USD")
    gbp = fx_realtime("GBP","USD")
    jpy = fx_realtime("USD","JPY")
    xau = None  # (You can add XAU via metals API later if needed)

    msg = [
        f"📊 <b>GTC Academy — Daily Market Snapshot</b>",
        now_utc(), "",
        fmt_pair_line("EUR/USD", eur),
        fmt_pair_line("GBP/USD", gbp),
        fmt_pair_line("USD/JPY", jpy),
        fmt_pair_line("XAU/USD", xau), ""
    ]

    headlines = top_headlines(3)
    if headlines:
        msg.append("🗞 <b>Top Headlines</b>")
        for t, s in headlines:
            src = f" <i>({s})</i>" if s else ""
            msg.append(f"• {t}{src}")
    tg_send_message("\n".join(msg))

def run_alert():
    # compare latest vs previous close (from FX_DAILY) and send if any > threshold
    pairs = [("EUR/USD", ("EUR","USD")),
             ("GBP/USD", ("GBP","USD")),
             ("USD/JPY", ("USD","JPY"))]
    lines = []
    fired = False
    for label, (a,b) in pairs:
        series = fx_daily_series(a,b)
        if len(series) < 2: 
            continue
        latest = series[0][1]; prev = series[1][1]
        chg = pct_change(latest, prev)
        if abs(chg) >= ALERT_THRESHOLD_PCT:
            fired = True
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(f"• {label}: {latest:.6f} ({arrow}{abs(chg):.2f}%)")
    if fired:
        msg = [f"🔔 <b>GTC Market Alert</b>", now_utc(), ""]
        msg.extend(lines)
        tg_send_message("\n".join(msg))

def run_weekly():
    # Use Friday-vs-previous-Friday (approx: 5 trading days back)
    eur = fx_daily_series("EUR","USD")
    gbp = fx_daily_series("GBP","USD")
    jpy = fx_daily_series("USD","JPY")
    btc = crypto_daily("BTC","USD")
    spy = equity_daily("SPY")

    def weekly_line(name: str, series: List[Tuple[str,float]]) -> str:
        if len(series) < 6: return f"• {name}: n/a"
        latest = series[0][1]; week_ago = series[5][1]  # ~5 sessions back
        chg = pct_change(latest, week_ago)
        arrow = "▲" if chg >= 0 else "▼"
        return f"• {name}: {latest:.4f} ({arrow}{abs(chg):.2f}% w/w)"

    msg = [
        f"🗓️ <b>GTC Weekly Market Recap</b>",
        now_utc(), "",
        weekly_line("EUR/USD", eur),
        weekly_line("GBP/USD", gbp),
        weekly_line("USD/JPY", jpy),
        weekly_line("BTC/USD", btc),
        weekly_line("SPY (S&P500)", spy), ""
    ]
    headlines = top_headlines(3)
    if headlines:
        msg.append("🗞 <b>Top Headlines</b>")
        for t,s in headlines:
            src = f" <i>({s})</i>" if s else ""
            msg.append(f"• {t}{src}")
    tg_send_message("\n".join(msg))

def run_chart():
    # Build a 30-day chart and post as image
    eur = fx_daily_series("EUR","USD")[:30]
    btc = crypto_daily("BTC","USD")[:30]
    spy = equity_daily("SPY")[:30]

    def add_series(ax, title: str, series: List[Tuple[str,float]]):
        if not series: 
            ax.set_title(f"{title} (n/a)"); return
        dates = [dt.datetime.strptime(d, "%Y-%m-%d") for d,_ in series][::-1]
        vals  = [v for _,v in series][::-1]
        ax.plot(dates, vals)
        ax.set_title(title)
        ax.grid(True, alpha=0.2)

    fig, axs = plt.subplots(3, 1, figsize=(8, 10), constrained_layout=True)
    add_series(axs[0], "EUR/USD — last 30 sessions", eur)
    add_series(axs[1], "BTC/USD — last 30 sessions", btc)
    add_series(axs[2], "SPY (S&P500) — last 30 sessions", spy)

    bio = io.BytesIO()
    fig.savefig(bio, format="png", dpi=150)
    plt.close(fig)
    tg_send_photo("📈 <b>Market Charts (30 sessions)</b>\n"+now_utc(), bio.getvalue())

# ------------- entry -------------
if __name__ == "__main__":
    try:
        if RUN_MODE == "daily":
            run_daily()
        elif RUN_MODE == "weekly":
            run_weekly()
        elif RUN_MODE == "chart":
            run_chart()
        else:
            run_alert()
    except Exception as e:
        tg_send_message(f"⚠️ <b>Bot error</b>: {e}")
        raise
