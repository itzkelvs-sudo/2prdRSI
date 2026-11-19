import os
import json
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

COOLDOWN_DAYS = 5


def send_telegram(message):

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message
        }
    )


def calculate_rsi(close, period=2):

    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def load_json(filename):

    try:

        with open(filename, "r") as f:
            return json.load(f)

    except:

        return {}


def save_json(filename, data):

    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


def in_cooldown(symbol, cooldowns):

    if symbol not in cooldowns:
        return False

    last_alert = datetime.fromisoformat(
        cooldowns[symbol]
    )

    days_since = (
        datetime.utcnow() - last_alert
    ).days

    return days_since < COOLDOWN_DAYS


# =====================================
# LOAD STATE
# =====================================

cooldowns = load_json(
    "cooldowns.json"
)

watchlist = load_json(
    "watchlist.json"
)

signals_found = 0
signal_tickers = []

send_telegram(
    "🚀 2prdRSI Scan Started"
)

# =====================================
# MARKET UNIVERSE
# =====================================

sp500_url = (
    "https://en.wikipedia.org/wiki/"
    "List_of_S%26P_500_companies"
)

sp500 = pd.read_html(
    sp500_url
)[0]

symbols = sp500["Symbol"].tolist()

etfs = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "SMH",
    "SOXX",
    "XLF",
    "XLK",
    "XLE",
    "XLV"
]

forex = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "AUDUSD=X",
    "NZDUSD=X",
    "USDCAD=X",
    "USDCHF=X"
]

crypto = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
    "AVAX-USD",
    "LINK-USD"
]

symbols.extend(etfs)
symbols.extend(forex)
symbols.extend(crypto)

# =====================================
# MAIN SCAN
# =====================================

for symbol in symbols:

    try:

        if in_cooldown(
            symbol,
            cooldowns
        ):
            continue

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if len(df) < 220:
            continue

        df["SMA200"] = (
            df["Close"]
            .rolling(200)
            .mean()
        )

        df["RSI2"] = calculate_rsi(
            df["Close"]
        )

        latest = df.iloc[-1]
        previous = df.iloc[-2]

        trend_filter = (
            latest["Close"]
            > latest["SMA200"]
        )

        lowest7 = (
            df["Low"]
            .tail(7)
            .min()
        )

        double7 = (
            latest["Low"]
            <= lowest7
        )

        oversold = (
            latest["RSI2"]
            < 5
        )

        # =====================================
        # STAGE 1
        # SETUP DETECTED
        # =====================================

        if (
            trend_filter
            and double7
            and oversold
            and symbol not in watchlist
        ):

            watchlist[symbol] = {
                "date":
                datetime.utcnow().isoformat()
            }

            send_telegram(
                f"""
🟡 SETUP DETECTED

{symbol}

RSI(2):
{latest['RSI2']:.2f}

Price:
${float
