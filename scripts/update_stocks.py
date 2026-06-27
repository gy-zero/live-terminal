import json
import os
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

import yfinance as yf

STOCKS_JSON_PATH = "stocks.json"

ASSETS = [
    {"symbol": "VOO", "display_name": "VOO", "currency": "USD", "market_type": "us_market"},
    {"symbol": "AAPL", "display_name": "AAPL", "currency": "USD", "market_type": "us_market"},
    {"symbol": "AMZN", "display_name": "AMZN", "currency": "USD", "market_type": "us_market"},
    {"symbol": "GOOG", "display_name": "GOOG", "currency": "USD", "market_type": "us_market"},
    {"symbol": "NVDA", "display_name": "NVDA", "currency": "USD", "market_type": "us_market"},
    {"symbol": "TSLA", "display_name": "TSLA", "currency": "USD", "market_type": "us_market"},
    {"symbol": "BTC-USD", "display_name": "BTCUSD", "currency": "USD", "market_type": "crypto_24_7"},
    {"symbol": "GC=F", "display_name": "Gold(CFD)", "currency": "USD", "market_type": "us_market"},
    {"symbol": "0050.TW", "display_name": "TPE:0050", "currency": "TWD", "market_type": "tw_market"},
    {"symbol": "2330.TW", "display_name": "TPE:2330", "currency": "TWD", "market_type": "tw_market"},
]

US_TZ = ZoneInfo("America/New_York")
TW_TZ = ZoneInfo("Asia/Taipei")
UTC_TZ = timezone.utc

US_REGULAR_CLOSE = time(16, 0)
TW_REGULAR_CLOSE = time(13, 30)

def now_iso():
    return datetime.now(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_previous_data():
    if not os.path.exists(STOCKS_JSON_PATH):
        return {}
    try:
        with open(STOCKS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def round_price(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except Exception:
        return None

def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def get_history(symbol):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1mo", interval="1d", auto_adjust=False)

    if hist is None or hist.empty or "Close" not in hist.columns:
        raise ValueError(f"{symbol} has no close history")

    hist = hist.copy()
    hist = hist[hist["Close"].notna()]

    if hist.empty:
        raise ValueError(f"{symbol} has empty close history after filtering")

    return ticker, hist

def normalize_history_records(hist):
    records = []
    for idx, row in hist.iterrows():
        close_value = safe_float(row.get("Close"))
        if close_value is None:
            continue

        if hasattr(idx, "to_pydatetime"):
            dt = idx.to_pydatetime()
        else:
            dt = idx

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)

        records.append({
            "dt": dt,
            "close": close_value
        })

    if not records:
        raise ValueError("No valid close records found")

    return records

def latest_completed_index(records, market_type, now_utc):
    if market_type == "crypto_24_7":
        return len(records) - 1

    if market_type == "us_market":
        market_now = now_utc.astimezone(US_TZ)
        market_close = US_REGULAR_CLOSE
    elif market_type == "tw_market":
        market_now = now_utc.astimezone(TW_TZ)
        market_close = TW_REGULAR_CLOSE
    else:
        raise ValueError(f"Unsupported market type: {market_type}")

    last_idx = len(records) - 1
    last_dt_local = records[last_idx]["dt"].astimezone(market_now.tzinfo)
    last_date_local = last_dt_local.date()
    today_local = market_now.date()

    if last_date_local < today_local:
        return last_idx

    if last_date_local > today_local:
        for i in range(last_idx, -1, -1):
            record_date = records[i]["dt"].astimezone(market_now.tzinfo).date()
            if record_date <= today_local:
                return i
        raise ValueError("No completed record at or before local today")

    if market_now.time() >= market_close:
        return last_idx

    if last_idx - 1 < 0:
        raise ValueError("Not enough completed history before today's close")
    return last_idx - 1

def extract_completed_closes(records, market_type):
    now_utc = datetime.now(UTC_TZ)
    current_idx = latest_completed_index(records, market_type, now_utc)

    if current_idx < 3:
        raise ValueError("Not enough completed close history")

    current = round_price(records[current_idx]["close"])
    prev = round_price(records[current_idx - 1]["close"])
    prev2 = round_price(records[current_idx - 2]["close"])
    prev3 = round_price(records[current_idx - 3]["close"])

    if None in (current, prev, prev2, prev3):
        raise ValueError("Incomplete completed close history")

    return current, prev, prev2, prev3

def get_crypto_current_price(ticker, fallback_close):
    fast_info = getattr(ticker, "fast_info", None)

    if fast_info:
        last_price = safe_float(fast_info.get("lastPrice"))
        if last_price is not None:
            return round_price(last_price)

        last_price = safe_float(fast_info.get("last_price"))
        if last_price is not None:
            return round_price(last_price)

    return round_price(fallback_close)

def build_asset(asset_def):
    symbol = asset_def["symbol"]
    market_type = asset_def["market_type"]

    ticker, hist = get_history(symbol)
    records = normalize_history_records(hist)

    current, prev, prev2, prev3 = extract_completed_closes(records, market_type)

    if market_type == "crypto_24_7":
        current = get_crypto_current_price(ticker, records[-1]["close"])

    if current is None or prev is None or prev2 is None or prev3 is None:
        raise ValueError(f"{symbol} has incomplete price data")

    return {
        "name": symbol,
        "display_name": asset_def["display_name"],
        "currency": asset_def["currency"],
        "current": current,
        "prev": prev,
        "prev2": prev2,
        "prev3": prev3,
        "stale": False
    }

def stale_asset(item):
    copied = dict(item)
    copied["stale"] = True
    return copied

def empty_asset(asset_def):
    return {
        "name": asset_def["symbol"],
        "display_name": asset_def["display_name"],
        "currency": asset_def["currency"],
        "current": None,
        "prev": None,
        "prev2": None,
        "prev3": None,
        "stale": True
    }

def main():
    previous_data = load_previous_data()
    previous_assets = {}

    for item in previous_data.get("assets", []):
        name = item.get("name")
        if name:
            previous_assets[name] = item

    assets = []

    for asset_def in ASSETS:
        symbol = asset_def["symbol"]
        try:
            assets.append(build_asset(asset_def))
        except Exception:
            if symbol in previous_assets:
                assets.append(stale_asset(previous_assets[symbol]))
            else:
                assets.append(empty_asset(asset_def))

    data = {
        "updated_at": now_iso(),
        "assets": assets
    }

    with open(STOCKS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
