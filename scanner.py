import json
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime

BOT_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

COOLDOWN_DAYS = 5


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        }
    )


def calculate_rsi(close, period=2):

    delta = close.diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def load_cooldowns():

    try:
        with open("cooldowns.json", "r") as f:
            return json.load(f)

    except:
        return {}


def save_cooldowns(data):

    with open("cooldowns.json", "w") as f:
        json.dump(data, f)


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


def update_cooldown(symbol, cooldowns):

    cooldowns[symbol] = (
        datetime.utcnow().isoformat()
    )


def scan_stock(symbol):

    df = yf.download(
        symbol,
        period="1y",
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    if len(df) < 250:
        return None

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
        latest["Close"] >
        latest["SMA200"]
    )

    double7 = (
        latest["Low"] <=
        df["Low"].tail(7).min()
    )

    oversold = (
        latest["RSI2"] < 5
    )

    reversal = (
        latest["RSI2"] >
        previous["RSI2"]
        and
        latest["Close"] >
        previous["Close"]
    )

    if not (
        trend_filter
        and double7
        and oversold
        and reversal
    ):
        return None

    if latest["RSI2"] < 1:
        quality = "🔴 EXTREME"
        stars = "★★★★★"

    elif latest["RSI2"] < 2:
        quality = "🟠 STRONG"
        stars = "★★★★"

    else:
        quality = "🟡 OVERSOLD"
        stars = "★★★"

    current_price = float(
        latest["Close"]
    )

    entry_limit = round(
        current_price * 0.998,
        2
    )

    target5 = round(
        df["High"].tail(5).max(),
        2
    )

    target7 = round(
        df["High"].tail(7).max(),
        2
    )

    return f"""
🔥 2prdRSI ENTRY SIGNAL

{symbol}

Price:
${current_price:.2f}

RSI(2):
{previous['RSI2']:.2f}
→
{latest['RSI2']:.2f}

Trend:
✅ Above 200 SMA

Double-7:
✅ New 7-Day Low

Entry Limit:
${entry_limit}

Target 1:
${target5}

Target 2:
${target7}

Quality:
{quality}

{stars}
"""


cooldowns = load_cooldowns()

with open("symbols.txt") as f:

    symbols = [
        x.strip()
        for x in f.readlines()
    ]

for symbol in symbols:

    if in_cooldown(
        symbol,
        cooldowns
    ):
        continue

    signal = scan_stock(symbol)

    if signal:

        send_telegram(signal)

        update_cooldown(
            symbol,
            cooldowns
        )

save_cooldowns(cooldowns)
