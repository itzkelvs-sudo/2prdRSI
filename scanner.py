import os
import requests
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


send_telegram("🚀 2prdRSI Scan Started")

symbols = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA"
]

signals_found = 0

for symbol in symbols:

    try:

        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        if len(df) < 20:
            continue

        send_telegram(
            f"✅ Tested {symbol}\nRows Downloaded: {len(df)}"
        )

    except Exception as e:

        send_telegram(
            f"❌ Error on {symbol}\n{str(e)}"
        )

send_telegram(
    f"""
✅ 2prdRSI Scan Complete

Stocks Scanned: {len(symbols)}

Signals Found: {signals_found}
"""
)
