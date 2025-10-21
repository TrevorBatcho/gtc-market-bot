import os, time, requests, asyncio
from datetime import time as dtime, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, ContextTypes
from telegram.request import HTTPXRequest

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")

# ==== Customize these ====
WATCHLIST = ["EURUSD", "XAUUSD", "GBPUSD", "USDJPY", "BTCUSD"]  # add/remove symbols
ALERT_MOVE_PCT = 0.5  # % move to trigger an alert
TZ = ZoneInfo("Asia/Dubai")  # change if you want another time zone
# =========================

session = requests.Session()

def get_fx_price(pair: str):
    url = ("https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE"
           f"&from_currency={pair[:3]}&to_currency={pair[3:]}&apikey={API_KEY}")
    try:
        data = session.get(url, timeout=15).json()
        return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    except Exception:
        return None

def get_crypto_price(symbol: str):
    coin = symbol[:-3]  # BTCUSD -> BTC
    url = ("https://www.alphavantage.co/query?function=CRYPTO_INTRADAY"
           f"&symbol={coin}&market=USD&interval=5min&apikey={API_KEY}")
    try:
        data = session.get(url, timeout=15).json()
        ts = data.get("Time Series Crypto (5min)") or {}
        if not ts: return None
        latest = sorted(ts.keys())[-1]
        return float(ts[latest]["4. close"])
    except Exception:
        return None

def price_for(symbol: str):
    if symbol.endswith("USD") and len(symbol) == 6:   # FX & XAUUSD
        return get_fx_price(symbol)
    if symbol.endswith("USD") and symbol[:3] in ("BTC","ETH"):
        return get_crypto_price(symbol)
    return get_fx_price(symbol)

def fmt(symbol, p):
    return f"{p:,.4f}" if symbol.endswith(("USD","JPY","INR")) else f"{p:,.2f}"

async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"📊 *GTC Academy Market Update*\n_{now}_\n"]
    last_prices = context.bot_data.setdefault("last_prices", {})
    for s in WATCHLIST:
        p = price_for(s)
        if p is None:
            lines.append(f"• {s}: data unavailable")
        else:
            lines.append(f"• {s}: {fmt(s, p)}")
            last_prices[s] = p
        time.sleep(12)  # respect Alpha Vantage free limits
    await context.bot.send_message(CHANNEL_ID, "\n".join(lines), parse_mode="Markdown")

async def instant_alerts(context: ContextTypes.DEFAULT_TYPE):
    last_prices = context.bot_data.setdefault("last_prices", {})
    for s in WATCHLIST:
        p = price_for(s)
        if p is None:
            continue
        old = last_prices.get(s)
        if old:
            move = (p - old) / old * 100
            if abs(move) >= ALERT_MOVE_PCT:
                arrow = "🔺" if move > 0 else "🔻"
                await context.bot.send_message(
                    CHANNEL_ID, f"{arrow} *{s}* moved {move:.2f}% → {fmt(s, p)}",
                    parse_mode="Markdown"
                )
                last_prices[s] = p
        else:
            last_prices[s] = p
        time.sleep(12)

async def on_startup(app):
    await app.bot.send_message(CHANNEL_ID, "🦉 GTC Market Bot is live. Daily 09:00 (Dubai) + 10-min alerts.")

