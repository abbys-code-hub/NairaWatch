import requests
import os
from dotenv import load_dotenv
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
import time

load_dotenv()


LOCAL_TZ = ZoneInfo("Africa/Lagos")
RATES_FILE = Path("rates.csv")
ALERT_LOWER = 1200.0
ALERT_UPPER = 2000.0
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
#     print("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
#     raise SystemExit(1)

URL = "https://open.er-api.com/v6/latest/USD"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nairawatch")

MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

def rate_date(updated):
    # try:
    #     return parsedate_to_datetime(updated).date().isoformat()
    # except (TypeError, ValueError):
    #     return datetime.now(timezone.utc).date().isoformat()

    try:
        published = parsedate_to_datetime(updated)
    except (TypeError, ValueError):
        published = datetime.now(timezone.utc)
    return published.astimezone(LOCAL_TZ).date().isoformat()

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
            
def is_retryable(error):
    """True for failures that might succeed on a second try"""
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        return status in RETRYABLE_STATUS_CODES
    return isinstance(error, (requests.ConnectionError, requests.Timeout))

def fetch_rate():
    data = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Fetchin USD rates (attempt %d/%d)", attempt, MAX_ATTEMPTS)

        try:
            response = requests.get(URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            break
        except requests.RequestException as e:
            if not is_retryable(e):
                logger.error("Fetch failed, not retrying: %s", e)
                return None
            if attempt == MAX_ATTEMPTS:
                logger.error("Fetch failed after %d attempts: %s", MAX_ATTEMPTS, type(e).__name__)
                return None
            wait = RETRY_WAIT_SECONDS *2 ** (attempt - 1)
            logger.warning("Attempt %d failed (%s), retrying in %ds", attempt, type(e).__name__, wait)
            time.sleep(wait)
 
    ngn_rate = data.get("rates", {}).get("NGN")
    updated = data.get("time_last_update_utc")
    if ngn_rate is None:
        logger.error("NGN rate not found in API response")
        return None
    logger.info("Fetched USD/NGN %s (source updated: %s)", ngn_rate, updated)
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
        # print(f"Error: could not send Telegram message ({type(e).__name__})")
        logger.error("Could not send Telegram message (%s)", type(e).__name__)
        return False
    logger.info("Telegram message sent")
    return True

def check_thresholds(rate, lower=ALERT_LOWER, upper=ALERT_UPPER):
    """Return an alert message if the rate is outside the range, else None."""
    if rate < lower:
        return f"ALERT: USD/NGN fell below {lower:,.2f} (now {rate:,.2f})"
    if rate > upper:
        return f"ALERT: USD/NGN rose above {upper:,.2f} (now {rate:,.2f})"
    return None

if __name__ == "__main__":
    logger.info("Run started")

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        # print("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
        logger.error("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
        raise SystemExit(1)

    
    result = fetch_rate()
    if result is None:
        raise SystemExit(1)

    rate, updated = result
    message = format_message(rate, updated)


    save_rate(rate, updated)

    if not send_telegram(message):
        raise SystemExit(1)

    alert = check_thresholds(rate)
    if alert:
        # print(alert)
        logger.warning("Threshold alert: %s", alert)
        if not send_telegram(alert):
            raise SystemExit(1)

    logger.info("Run finished")
