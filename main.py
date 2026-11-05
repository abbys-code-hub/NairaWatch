import requests
import os
from dotenv import load_dotenv
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RATES_FILE = Path("rates.csv")


load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
    raise SystemExit(1)

URL = "https://open.er-api.com/v6/latest/USD"

def rate_date(updated):
    try:
        return parsedate_to_datetime(updated).date().isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date().isoformat()

def save_rate(rate, updated):
    date_str = rate_date(updated)

    needs_header = not RATES_FILE.exists() or RATES_FILE.stat().st_size == 0

 
    if not needs_header:
        with open(RATES_FILE, newline="") as f:
            saved_dates = {row["date"] for row in csv.DictReader(f)}
        if date_str in saved_dates:
            print(f"\nRate for {date_str} already saved, skipping")
            return False

        # write_header = not RATES_FILE.exists()
    with open(RATES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if needs_header:
            writer.writerow(["date", "rate"])
        writer.writerow([date_str, rate])
    print(f"\nSaved rate for {date_str}")
    return True
            

def fetch_rate():
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"Error: request failed ({e})")
        return None
 
    ngn_rate = data.get("rates", {}).get("NGN")
    updated = data.get("time_last_update_utc")
    if ngn_rate is None:
        print("Error: NGN rate not found in response")
        return None
    return ngn_rate, updated



def format_message(rate, updated):
    updated_text = updated or "unknown"
    return f"USD/NGN: {rate:,.2f}\nRate updated at: {updated_text}"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error: could not send Telegram message ({type(e).__name__})")
        return False
    return True


if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
        raise SystemExit(1)

    
    result = fetch_rate()
    if result is None:
        raise SystemExit(1)
    rate, updated = result
    message = format_message(rate, updated)
    print(message)


    save_rate(rate, updated)

    if not send_telegram(message):
        raise SystemExit(1)
