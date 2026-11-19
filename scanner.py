import json
import os
from datetime import datetime

import requests
import yfinance as yf
import pandas as pd

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

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


def update_cooldown(symbol, cooldowns):

    cooldowns[symbol] = (
        datetime.utcnow().isoformat()
    )


def scan_stock(symbol):

    try:

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        if len(df) < 220:
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

        lowest7 = (
            df["Low"]
            .rolling(7)
            .min()
            .iloc[-1]
        )

        double7 = (
            latest["Low"] <= lowest7
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

        if not all([
            trend_filter,
            double7,
            oversold,
            reversal
        ]):
            return None

        rsi_value = float(latest["RSI2"])

        if rsi_value < 1:
            quality = "🔴 EXTREME"
            stars = "★★★★★"

        elif rsi_value < 2:
            quality = "🟠 STRONG"
            stars = "★★★★"

        else:
            quality = "🟡 OVERSOLD"
            stars = "★★★"

        close = float(latest["Close"])

        entry_limit = round(
            close * 0.998,
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

        message = f"""
🔥 2prdRSI ENTRY SIGNAL

{symbol}

━━━━━━━━━━━

Price
${close}

RSI(2)
{previous['RSI2']:.2f} → {latest['RSI2']:.2f}

Trend
✅ Above 200 SMA

Double-7
✅ New 7-Day Low

━━━━━━━━━━━

ENTRY LIMIT
${entry_limit}

TARGET 1
${target5}

TARGET 2
${target7}

━━━━━━━━━━━

QUALITY

{quality}
{stars}
"""

        return message

    except Exception as e:

        print(
            f"Error scanning {symbol}: {e}"
        )

        return None


cooldowns = load_cooldowns()

with open("symbols.txt", "r") as f:
    symbols = [
        s.strip()
        for s in f.readlines()
        if s.strip()
    ]

signals_found = 0

for symbol in symbols:

    if in_cooldown(symbol, cooldowns):
        continue

    signal = scan_stock(symbol)

    if signal:

        send_telegram(signal)

        signals_found += 1

        update_cooldown(
            symbol,
            cooldowns
        )

save_cooldowns(cooldowns)

if signals_found == 0:

    send_telegram(
        f"""
✅ 2prdRSI Scan Complete

Stocks Scanned: {len(symbols)}

No qualifying setups found.
"""
    )

else:

    send_telegram(
        f"""
✅ 2prdRSI Scan Complete

Stocks Scanned: {len(symbols)}

Signals Found: {signals_found}
"""
    )

print("Scan complete.")
    )

print("Scan complete.")
