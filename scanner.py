import os
import requests
import pandas as pd
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


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


send_telegram("🚀 2prdRSI Scan Started")

# ===========================
# MARKET UNIVERSE
# ===========================

sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

sp500 = pd.read_html(sp500_url)[0]

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

signals_found = 0
signal_tickers = []

# ===========================
# SCANNER
# ===========================

for symbol in symbols:

    try:

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        if len(df) < 200:
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

        trend_filter = (
            latest["Close"]
            > latest["SMA200"]
        )

        lowest_7 = (
            df["Low"]
            .tail(7)
            .min()
        )

        double7 = (
            latest["Low"]
            <= lowest_7
        )

        oversold = (
            latest["RSI2"]
            < 5
        )

        if (
            trend_filter
            and double7
            and oversold
        ):

            signals_found += 1
            signal_tickers.append(symbol)

            close = round(
                float(latest["Close"]),
                2
            )

            rsi_value = round(
                float(latest["RSI2"]),
                2
            )

            entry_limit = round(
                close * 0.998,
                2
            )

            target5 = round(
                float(
                  
