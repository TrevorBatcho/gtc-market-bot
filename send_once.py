# send_once.py
import os, requests, datetime
from dotenv import load_dotenv
load_dotenv()  # still safe if present locally; GH Actions uses secrets

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHANNEL_ID")           # e.g. -1001234567890
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")

if not TOKEN or not CHAT_ID or not API_KEY:
    raise SystemExit("Missing TELEGRAM_TOKEN, CHANNEL_ID or ALPHA_VANTAGE_KEY")

def fetch_fx(from_cur="EUR", to_cur="USD"):
    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={from_cur}&to_currency={to_cur}&apikey={API_KEY}"
    r = requests.get(url, timeout=20).json()
    # parse safely
    try:
        d = r["Realtime Currency Exchange Rate"]
        rate = d.get("5. Exchange Rate")
        return f"{from_cur}/{to_cur}: {rate}"
    except Exception as e:
        return f"Error fetching {from_cur}/{to_cur}: {e}"

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    r = requests.post(url, data=payload, timeout=20)
    return r.ok, r.text

def main(mode="alert"):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    if mode == "daily":
        header = f"🦉 <b>GTC Academy — Daily Market Snapshot</b>\n{timestamp}\n\n"
        lines = [
            fetch_fx("EUR","USD"),
            fetch_fx("GBP","USD"),
            fetch_fx("USD","JPY")
            # add more pairs if you want
        ]
        text = header + "\n".join(lines)
    else:  # alert
        header = f"🔔 <b>GTC Market Alert</b>\n{timestamp}\n\n"
        # sample: snapshot of EURUSD only for alerts; you can compute percent moves inside script
        text = header + fetch_fx("EUR","USD")
    ok, resp = send_message(text)
    if not ok:
        print("Send failed:", resp)
        raise SystemExit(1)
    print("Sent OK:", text[:80])

if __name__ == "__main__":
    # mode passed via env var in Actions; default = alert
    mode = os.getenv("RUN_MODE", "alert")
    main(mode=mode)
