#!/usr/bin/env python3
"""
Pipeline A: 0.5% 波动即时提醒

每次运行:
  1. 读取 config/watchlist.json 里的股票列表
  2. 通过 Finnhub 查询每个标的当日涨跌幅 (相对前一交易日收盘价)
  3. 如果涨跌幅"跨越"了一个新的 0.5% 整数倍阈值
     (比如从 +0.3% 变成 +0.7%,跨过了 +0.5% 这一档),
     就通过 ntfy.sh 推送一条文字通知。
  4. 当天每个标的第一次被记录时只建立基准、不发提醒,
     避免开盘第一轮就因为隔夜跳空而集中推送一大堆通知。
  5. 状态保存在 state/alert_state.json,每天自动重置。
"""

import json
import os
from datetime import date

import requests

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
THRESHOLD = float(os.environ.get("ALERT_THRESHOLD_PCT", "0.5"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_PATH = os.path.join(BASE_DIR, "config", "watchlist.json")
STATE_PATH = os.path.join(BASE_DIR, "state", "alert_state.json")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_quote(symbol):
    """调用 Finnhub /quote。失败或数据无效时返回 None 并打印原因。"""
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": FINNHUB_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[警告] {symbol} 请求失败: {e}")
        return None

    price = data.get("c")
    pct = data.get("dp")

    # Finnhub 对不支持/查不到的代码通常返回全 0,这里视为无效数据
    if price in (None, 0) and pct in (None, 0):
        print(f"[跳过] {symbol} 无有效报价(可能 Finnhub 免费版不支持该代码)")
        return None

    if pct is None:
        print(f"[跳过] {symbol} 缺少涨跌幅数据")
        return None

    return {"price": price, "pct": pct, "change": data.get("d")}


def pct_bucket(pct):
    """把涨跌幅换算成以 THRESHOLD 为单位的整数档位,正负号代表方向。"""
    sign = 1 if pct >= 0 else -1
    return sign * int(abs(pct) // THRESHOLD)


def send_ntfy(symbol, pct, price):
    direction = "上涨" if pct >= 0 else "下跌"
    title = f"{symbol} 异动提醒"
    message = f"{symbol} 今日{direction} {abs(pct):.2f}%,现价 {price}"

    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": 4,
        "tags": [
            "chart_with_upwards_trend" if pct >= 0 else "chart_with_downwards_trend"
        ],
    }

    try:
        requests.post("https://ntfy.sh/", json=payload, timeout=10)
        print(f"[已推送] {message}")
    except Exception as e:
        print(f"[警告] 推送失败 {symbol}: {e}")


def main():
    watchlist = load_json(WATCHLIST_PATH, [])
    today = date.today().isoformat()

    state = load_json(STATE_PATH, {"date": today, "tickers": {}})
    if state.get("date") != today:
        state = {"date": today, "tickers": {}}

    changed = False
    alert_count = 0

    for symbol in watchlist:
        quote = get_quote(symbol)
        if quote is None:
            continue

        bucket = pct_bucket(quote["pct"])
        prev_bucket = state["tickers"].get(symbol)

        if prev_bucket is None:
            # 今天第一次记录该标的:只建立基准,不发提醒
            state["tickers"][symbol] = bucket
            changed = True
            continue

        if bucket != prev_bucket:
            state["tickers"][symbol] = bucket
            changed = True
            if abs(bucket) >= 1:
                send_ntfy(symbol, quote["pct"], quote["price"])
                alert_count += 1

    if changed:
        save_json(STATE_PATH, state)

    print(f"本轮完成,共触发 {alert_count} 条提醒。")


if __name__ == "__main__":
    main()
