# bybit_bot_rsi_breakout_optimized.py
# ✅ Improved Bot: Breakout + Volume Spike (2x) + EMA + RSI Filter + ATR Guard + RR 2.5

import time
from datetime import datetime, timezone
import requests
import numpy as np
from pybit.unified_trading import HTTP
import os
from keep_alive import keep_alive
keep_alive()
# === CONFIG ===
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE", 5))
RR = 2.5
ATR_MULTIPLIER = 1.2
SYMBOL = "XRPUSDT"
INTERVAL = "1"  # 1-minute
CATEGORY = "linear"
POLL_INTERVAL = 10


API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=False)
open_trade = None

# === UTILS ===
def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram error:", e)

def fetch_ohlcv(symbol, interval='1', limit=50):
    try:
        ohlcv = client.get_kline(category=CATEGORY, symbol=symbol, interval=interval, limit=limit)
        return [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in ohlcv['result']['list']][::-1]
    except:
        return []

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    ups = np.where(deltas > 0, deltas, 0)
    downs = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(ups[-period:])
    avg_loss = np.mean(downs[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_atr(candles, period=14):
    trs = [
        max(c[2] - c[3], abs(c[2] - candles[i-1][4]), abs(c[3] - candles[i-1][4]))
        for i, c in enumerate(candles[1:], 1)
    ]
    return np.mean(trs[-period:]) if len(trs) >= period else None

# === STRATEGY LOGIC ===
def signal(candles):
    prices = [c[4] for c in candles]
    volumes = [c[5] for c in candles]
    price = prices[-1]
    high20 = max(c[2] for c in candles[-20:-1])
    low20 = min(c[3] for c in candles[-20:-1])
    vol_spike = volumes[-1] > 2.0 * np.mean(volumes[-20:-1])
    ema20 = np.mean(prices[-20:])
    rsi = calculate_rsi(prices)

    if candles[-1][2] - candles[-1][3] < 0.001:
        return False, False, price

    long_signal = price > high20 and vol_spike and price > ema20 and rsi > 55
    short_signal = price < low20 and vol_spike and price < ema20 and rsi < 45

    return long_signal, short_signal, price

# === MAIN LOOP ===
send_telegram("🚀 Optimized Breakout Bot Started")

loop_counter = 0

while True:
    try:
        pos = client.get_positions(category=CATEGORY, symbol=SYMBOL)['result']['list'][0]
        size = float(pos['size'])
        entry = float(pos['avgPrice']) if size > 0 else None

        if size == 0 and open_trade:
            last_price = float(client.get_tickers(category=CATEGORY, symbol=SYMBOL)['result']['list'][0]['lastPrice'])
            pnl = round((last_price - open_trade['entry']) * open_trade['qty'] if open_trade['side'] == 'buy' else (open_trade['entry'] - last_price) * open_trade['qty'], 2)
            result = "✅ PROFIT" if pnl > 0.1 else "🔄 BREAKEVEN" if abs(pnl) <= 0.1 else "❌ LOSS"
            send_telegram(f"{result} [{SYMBOL}]\nPnL: {pnl} USDT")
            open_trade = None

        if size > 0:
            time.sleep(POLL_INTERVAL)
            continue

        candles = fetch_ohlcv(SYMBOL, INTERVAL, 50)
        if len(candles) < 30:
            time.sleep(POLL_INTERVAL)
            continue

        go_long, go_short, price = signal(candles)
        atr = calculate_atr(candles)
        if not atr:
            time.sleep(POLL_INTERVAL)
            continue

        if loop_counter % 30 == 0:
            send_telegram(f"⏱️ Status\nSymbol: {SYMBOL}\nPrice: {price}\nATR: {round(atr, 5)}\nLONG: {go_long} | SHORT: {go_short}")

        if go_long:
            sl = price - atr * ATR_MULTIPLIER
            tp = price + atr * ATR_MULTIPLIER * RR
            direction = 'Buy'
        elif go_short:
            sl = price + atr * ATR_MULTIPLIER
            tp = price - atr * ATR_MULTIPLIER * RR
            direction = 'Sell'
        else:
            time.sleep(POLL_INTERVAL)
            loop_counter += 1
            continue

        qty = max(int(RISK_PER_TRADE / abs(price - sl)), 1)

        client.place_order(
            category=CATEGORY,
            symbol=SYMBOL,
            side=direction,
            orderType="Market",
            qty=qty,
            takeProfit=round(tp, 5),
            stopLoss=round(sl, 5),
            timeInForce="GTC"
        )

        open_trade = {'side': direction.lower(), 'entry': price, 'qty': qty, 'tp': tp, 'sl': sl}

        send_telegram(f"📈 ENTRY [{SYMBOL}]\nSide: {direction}\nPrice: {price}\nTP: {tp}\nSL: {sl}")
        send_telegram(f"⚙️ Order Details\nSL: {round(sl, 5)}\nTP: {round(tp, 5)}\nQty: {qty}")

    except Exception as e:
        send_telegram(f"⚠️ Error: {e}")

    loop_counter += 1
    time.sleep(POLL_INTERVAL)
