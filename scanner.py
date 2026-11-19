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
        },
        timeout=30
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
    except Exception:
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


# ==================================
# LOAD STATE
# ==================================

cooldowns = load_json("cooldowns.json")
watchlist = load_json("watchlist.json")

signals_found = 0
signal_tickers = []

send_telegram("🚀 2prdRSI Scan Started")

# ==================================
# BUILD MARKET UNIVERSE
# ==================================

sp500_url = (
    "https://en.wikipedia.org/wiki/"
    "List_of_S%26P_500_companies"
)

sp500 = pd.read_html(sp500_url)[0]

symbols = sp500["Symbol"].tolist()

etfs = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "SMH",
    "SOXX",
    "XLK",
    "XLF",
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
    "DOGE-USD"
]

symbols.extend(etfs)
symbols.extend(forex)
symbols.extend(crypto)

# Remove duplicates
symbols = list(dict.fromkeys(symbols))

# ==================================
# MAIN SCAN
# ==================================

for symbol in symbols:

    try:

        if in_cooldown(symbol, cooldowns):
            continue

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False
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
            latest["RSI2"] < 5
        )

        setup_detected = (
            trend_filter
            and double7
            and oversold
        )

        # ==========================
        # STAGE 1
        # ==========================

        if (
            setup_detected
            and symbol not in watchlist
        ):

            watchlist[symbol] = {
                "date": datetime.utcnow().isoformat()
            }

            send_telegram(
                f"""🟡 SETUP DETECTED

{symbol}

RSI(2): {latest['RSI2']:.2f}

Price: ${float(latest['Close']):.2f}

✅ Above 200 SMA
✅ Double-7 Low

Waiting for reversal confirmation."""
            )

        # ==========================
        # STAGE 2
        # ==========================

        if symbol in watchlist:

            reversal = (
                latest["RSI2"] > previous["RSI2"]
                and
                latest["Close"] > previous["Close"]
            )

            if reversal:

                close_price = float(
                    latest["Close"]
                )

                entry_limit = round(
                    close_price * 0.998,
                    2
                )

                target5 = round(
                    float(
                        df["High"]
                        .tail(5)
                        .max()
                    ),
                    2
                )

                target7 = round(
                    float(
                        df["High"]
                        .tail(7)
                        .max()
                    ),
                    2
                )

                send_telegram(
                    f"""🚀 ENTRY CONFIRMED

{symbol}

RSI(2):
{previous['RSI2']:.2f} → {latest['RSI2']:.2f}

Current Price:
${close_price:.2f}

Entry Limit:
${entry_limit}

Target 1:
${target5}

Target 2:
${target7}"""
                )

                cooldowns[symbol] = (
                    datetime.utcnow()
                    .isoformat()
                )

                del watchlist[symbol]

                signals_found += 1
                signal_tickers.append(symbol)

    except Exception as e:
        print(f"{symbol} error: {e}")

# ==================================
# SAVE STATE
# ==================================

save_json(
    "cooldowns.json",
    cooldowns
)

save_json(
    "watchlist.json",
    watchlist
)

# ==================================
# SUMMARY
# ==================================

if signals_found == 0:

    send_telegram(
        f"""✅ 2prdRSI Scan Complete

Markets Scanned: {len(symbols)}

Watchlist Size: {len(watchlist)}

Confirmed Entries: 0"""
    )

else:

    tickers = ", ".join(signal_tickers)

    send_telegram(
        f"""✅ 2prdRSI Scan Complete

Markets Scanned: {len(symbols)}

Watchlist Size: {len(watchlist)}

Confirmed Entries: {signals_found}

Signals:
{tickers}"""
    )

print("Scan complete.")
