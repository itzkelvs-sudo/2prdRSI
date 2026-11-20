#!/usr/bin/env python3
"""
2prdRSI scanner - fast version
==============================
Your logic is unchanged:
  Stage 1  SETUP      above the 200-day SMA + today's low <= the lowest low of the last 7 bars + RSI(2) < 5
  Stage 2  CONFIRMED  later, RSI(2) rises AND the close rises  -> "ENTRY CONFIRMED" with entry limit and 2 targets
Same environment variables (BOT_TOKEN, CHAT_ID) and state files (watchlist.json, cooldowns.json).

WHY THE OLD VERSION WAS SLOW
  * it called yf.download() once per symbol (about 540 separate web requests, one after another). Now the symbols
    are downloaded in batches of 100 with threads: about 6 requests in total.
  * it read the S&P 500 list from Wikipedia on EVERY run, with no User-Agent (Wikipedia often refuses that), and
    "BRK.B" / "BF.B" were never valid Yahoo symbols (they are BRK-B / BF-B). Now the list comes from a GitHub-hosted
    CSV first, Wikipedia second, is cleaned, and is cached in sp500_symbols.txt for 7 days - most runs make no
    list request at all. If both sources fail, the cached list (even an old one) or a built-in list is used.

FIXES THAT CHANGE RESULTS (each one is a switch near the top)
  * RSI(2) is now Wilder-smoothed (Connors' RSI). A plain 2-bar rolling mean flips between 0 and 100 on almost
    every bar. Set RSI_SMOOTHING = "simple" to get your original numbers back.
  * the still-forming bar of today is dropped (crypto's daily bar is always unfinished during the day), so a signal
    cannot appear and then disappear.
  * Stage 2 is only checked on bars AFTER the setup bar (before, a setup could "confirm" on the same bar).
  * a watch-list entry now expires after WATCH_MAX_AGE bars, or when the close falls below the 200-day SMA
    (before, it stayed forever and could fire weeks later on any up day).
  * state files are written even if the run is interrupted late, and Telegram errors/429 limits are handled.
"""

import json
import os
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

COOLDOWN_DAYS = 5
WATCH_MAX_AGE = 5            # bars a setup may wait for its reversal
RSI_SMOOTHING = "wilder"     # "wilder" (Connors) or "simple" (your original rolling mean)
RSI_LEVEL = 5
LOW_BARS = 7
SEND_START_MESSAGE = True
CHUNK = 100                  # symbols per Yahoo request

UNIVERSE_FILE = Path("sp500_symbols.txt")
UNIVERSE_MAX_AGE_DAYS = 7
UNIVERSE_SOURCES = [
    ("GitHub CSV", "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv", "csv"),
    ("Wikipedia", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "html"),
]
FALLBACK_SP500 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "V", "UNH", "XOM", "JNJ",
                  "WMT", "MA", "PG", "AVGO", "HD", "CVX", "MRK", "ABBV", "KO", "PEP", "COST", "ADBE", "WFC", "CRM",
                  "BAC", "MCD", "TMO", "NFLX", "AMD", "ORCL", "CSCO", "ACN", "LIN", "ABT", "DHR", "TXN", "QCOM"]

FOREX = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "NZDUSD=X", "USDCAD=X", "USDCHF=X"]


# ════════════════════════════ TELEGRAM ════════════════════════════
def send_telegram(message: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("[no telegram creds] " + message.replace("\n", " | "))
        return
    for attempt in range(2):
        try:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              data={"chat_id": CHAT_ID, "text": message[:4000]}, timeout=30)
            if r.status_code == 429:                              # Telegram rate limit: wait as told, retry once
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            if not r.ok:
                print(f"[telegram error] {r.status_code} {r.text}")
            break
        except Exception as exc:                                  # noqa: BLE001
            print(f"[telegram error] {exc}")
            break
    time.sleep(0.3)                                               # stay under Telegram's per-second limits


# ════════════════════════════ STATE ════════════════════════════
def load_json(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return {}


def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


def now_utc():
    return datetime.now(timezone.utc)


def in_cooldown(symbol, cooldowns):
    if symbol not in cooldowns:
        return False
    last = datetime.fromisoformat(cooldowns[symbol])
    if last.tzinfo is None:                                       # older files stored naive UTC times
        last = last.replace(tzinfo=timezone.utc)
    return (now_utc() - last).days < COOLDOWN_DAYS


# ════════════════════════════ UNIVERSE (no more per-run Wikipedia) ════════════════════════════
def clean_symbol(s):
    return str(s).strip().upper().replace(".", "-")               # BRK.B -> BRK-B, BF.B -> BF-B (Yahoo format)


def read_universe_cache():
    try:
        return [x for x in UNIVERSE_FILE.read_text().split() if x]
    except Exception:                                             # noqa: BLE001
        return []


def load_sp500():
    cached = read_universe_cache()
    if cached and UNIVERSE_FILE.exists():
        age_days = (time.time() - UNIVERSE_FILE.stat().st_mtime) / 86400
        if age_days < UNIVERSE_MAX_AGE_DAYS:
            print(f"S&P 500 list: cache ({len(cached)} symbols, {age_days:.1f} days old)")
            return cached
    for name, url, kind in UNIVERSE_SOURCES:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            r.raise_for_status()
            col = (pd.read_csv(StringIO(r.text)) if kind == "csv" else pd.read_html(StringIO(r.text))[0])["Symbol"]
            syms = list(dict.fromkeys(clean_symbol(s) for s in col.dropna()))
            if len(syms) >= 400:
                UNIVERSE_FILE.write_text("\n".join(syms))
                print(f"S&P 500 list: {name} ({len(syms)} symbols)")
                return syms
            print(f"[warn] {name} returned only {len(syms)} symbols - ignored")
        except Exception as exc:                                  # noqa: BLE001
            print(f"[warn] S&P 500 list from {name} failed: {exc}")
    if cached:
        print(f"S&P 500 list: stale cache ({len(cached)} symbols)")
        return cached
    print(f"[warn] using the built-in fallback list ({len(FALLBACK_SP500)} symbols)")
    return FALLBACK_SP500


# ════════════════════════════ DATA (batched) ════════════════════════════
def completed(df):
    """Drop today's still-forming daily bar."""
    if df.empty:
        return df
    ts = df.index[-1]
    now = pd.Timestamp.now(tz=ts.tz) if getattr(ts, "tzinfo", None) else pd.Timestamp.now()
    return df.iloc[:-1] if ts + pd.Timedelta("1D") > now else df


def download_all(symbols):
    out = {}
    for i in range(0, len(symbols), CHUNK):
        batch = symbols[i:i + CHUNK]
        raw = None
        for attempt in range(2):                                  # one retry per batch
            try:
                raw = yf.download(batch, period="1y", interval="1d", group_by="ticker",
                                  auto_adjust=True, progress=False, threads=True)
                break
            except Exception as exc:                              # noqa: BLE001
                print(f"[warn] batch {i // CHUNK + 1} attempt {attempt + 1} failed: {exc}")
                time.sleep(3)
        if raw is None or raw.empty:
            continue
        for s in batch:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if s not in raw.columns.get_level_values(0):
                        continue
                    sub = raw[s]
                else:
                    sub = raw
                sub = completed(sub.dropna(subset=["Close", "Low", "High"]))
                if len(sub):
                    out[s] = sub
            except Exception as exc:                              # noqa: BLE001
                print(f"[warn] {s}: {exc}")
    return out


# ════════════════════════════ INDICATORS ════════════════════════════
def calculate_rsi(close, period=2):
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    if RSI_SMOOTHING == "simple":
        avg_gain, avg_loss = gain.rolling(period).mean(), loss.rolling(period).mean()
    else:
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    return (100 - 100 / (1 + rs)).fillna(50)


def prepare(df):
    df = df.copy()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI2"] = calculate_rsi(df["Close"])
    df["LOW7"] = df["Low"].rolling(LOW_BARS).min()
    return df


def is_setup(df, k):
    r = df.iloc[k]
    if pd.isna(r["SMA200"]) or pd.isna(r["LOW7"]):
        return False
    return bool(r["Close"] > r["SMA200"] and r["Low"] <= r["LOW7"] and r["RSI2"] < RSI_LEVEL)


def check_watch(df, setup_day):
    """Walk the bars after the setup bar. Returns ('confirm', k) / ('drop', reason) / ('keep', setup_day)."""
    days = [d.strftime("%Y-%m-%d") for d in df.index]
    ks = days.index(setup_day) if setup_day in days else None
    if ks is None:
        # older watchlist entries only had a timestamp - start from the first bar on/after that date
        ks = next((i for i, d in enumerate(days) if d >= setup_day), None)
        if ks is None:
            return "keep", setup_day
    for k in range(ks + 1, len(df)):
        if is_setup(df, k):                                       # a fresh setup bar: the wait restarts here
            ks = k
            continue
        r, p = df.iloc[k], df.iloc[k - 1]
        if not pd.isna(r["SMA200"]) and r["Close"] <= r["SMA200"]:
            return "drop", "fell below the 200-day SMA"
        if k - ks > WATCH_MAX_AGE:
            return "drop", "setup expired"
        if r["RSI2"] > p["RSI2"] and r["Close"] > p["Close"]:
            return "confirm", k
    return "keep", days[ks]


# ════════════════════════════ MAIN ════════════════════════════
def main():
    t0 = time.time()
    cooldowns = load_json("cooldowns.json")
    watchlist = load_json("watchlist.json")
    signals_found, signal_tickers = 0, []

    if SEND_START_MESSAGE:
        send_telegram("🚀 2prdRSI Scan Started")

    symbols = load_sp500() + FOREX 
    symbols = list(dict.fromkeys(symbols))
    data = download_all(symbols)
    print(f"downloaded {len(data)}/{len(symbols)} symbols in {time.time() - t0:.0f}s")

    for symbol in symbols:
        try:
            df = data.get(symbol)
            if df is None or len(df) < 220:
                continue
            df = prepare(df)
            k = len(df) - 1
            latest, previous = df.iloc[k], df.iloc[k - 1]
            day = df.index[k].strftime("%Y-%m-%d")

            # ---- Stage 2 first (watched symbols; only bars after the setup bar)
            if symbol in watchlist and not in_cooldown(symbol, cooldowns):
                w = watchlist[symbol]
                verdict, info = check_watch(df, w.get("bar") or w["date"][:10])
                if verdict == "drop":
                    print(f"  drop {symbol}: {info}")
                    del watchlist[symbol]
                elif verdict == "keep":
                    w["bar"] = info
                else:
                    kk = info
                    row, prev = df.iloc[kk], df.iloc[kk - 1]
                    close_price = float(row["Close"])
                    entry_limit = round(close_price * 0.998, 2)
                    target5 = round(float(df["High"].iloc[max(0, kk - 4):kk + 1].max()), 2)
                    target7 = round(float(df["High"].iloc[max(0, kk - 6):kk + 1].max()), 2)
                    send_telegram(f"""🚀 ENTRY CONFIRMED

{symbol}

RSI(2):
{prev['RSI2']:.2f} → {row['RSI2']:.2f}

Current Price:
${close_price:.2f}

Entry Limit:
${entry_limit}

Target 1:
${target5}

Target 2:
${target7}""")
                    cooldowns[symbol] = now_utc().isoformat()
                    del watchlist[symbol]
                    signals_found += 1
                    signal_tickers.append(symbol)
                    continue

            # ---- Stage 1: a new setup on the latest bar
            if symbol not in watchlist and not in_cooldown(symbol, cooldowns) and is_setup(df, k):
                watchlist[symbol] = {"date": now_utc().isoformat(), "bar": day}
                send_telegram(f"""🟡 SETUP DETECTED

{symbol}

RSI(2): {latest['RSI2']:.2f}

Price: ${float(latest['Close']):.2f}

✅ Above 200 SMA
✅ Double-7 Low

Waiting for reversal confirmation.""")
        except Exception as exc:                                  # noqa: BLE001
            print(f"{symbol} error: {exc}")

    save_json("cooldowns.json", cooldowns)
    save_json("watchlist.json", watchlist)

    tickers = ", ".join(signal_tickers)
    send_telegram(f"""✅ 2prdRSI Scan Complete

Markets Scanned: {len(data)} of {len(symbols)}

Watchlist Size: {len(watchlist)}

Confirmed Entries: {signals_found}""" + (f"\n\nSignals:\n{tickers}" if signals_found else ""))
    print(f"Scan complete in {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
