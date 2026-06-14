#!/usr/bin/env python3
"""
Pipeline B - Step 1: 生成播客对话脚本

读取 config/core_list.json 里的核心持仓,用 Finnhub 拉取当日数据,
交给 Claude(开启 web_search)生成一段双主播对话稿。

这一步先验证"内容质量",还不涉及语音合成和发布——
脚本会打印到日志、并写入 output/latest_episode.md,方便在GitHub上直接阅读。
"""

import json
import os
from datetime import date

import requests
from anthropic import Anthropic

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_LIST_PATH = os.path.join(BASE_DIR, "config", "core_list.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "output", "latest_episode.md")

HOST_A = "阿哲"  # 偏宏观与框架性分析
HOST_B = "小晴"  # 偏个股、盘面与市场情绪


def load_core_list():
    with open(CORE_LIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_quote(symbol):
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
    if price in (None, 0) and pct in (None, 0):
        return None
    return {"price": price, "pct": pct}


def build_data_table(core_list):
    lines = []
    for symbol in core_list:
        q = get_quote(symbol)
        if q is None:
            lines.append(f"- {symbol}: (今日数据暂不可用)")
        else:
            sign = "+" if q["pct"] >= 0 else ""
            lines.append(f"- {symbol}: 现价 {q['price']}, 当日 {sign}{q['pct']:.2f}%")
    return "\n".join(lines)


def build_prompt(data_table, today_str):
    return f"""你正在为一档面向资深个人投资者的中文财经播客撰写对话脚本。

两位主播:
- {HOST_A}:偏宏观与框架性分析,会引用 Howard Marks、Damodaran 等人的视角看待周期和估值
- {HOST_B}:偏个股、盘面与市场情绪,关注社交媒体热度、资金流向和技术面

两人风格互补、对话自然、偶有观点碰撞,整体专业克制。
避免空洞套话和简单的多空站队,更看重逻辑和证据,保持怀疑式、结构化的分析风格。

今天是{today_str}。以下是听众核心持仓的当日数据(来自Finnhub,
少数标的可能暂无数据):

{data_table}

请完成两部分内容:

【第一部分:核心持仓点评】
针对以上每一个标的,结合当日涨跌,简要分析当天可能的驱动因素
(如有必要可以搜索当天相关新闻),并给出对接下来1-2个交易日走势的看法。
每个标的不需要展开很长,但都要点到。对于暂无数据的标的,
可以基于你对该公司/产品近期情况的了解给出简要观察,不要编造具体数字。

【第二部分:市场热门股扫描】
搜索今天美股市场和社交媒体(Reddit、Stocktwits、X等)上讨论度较高、
但不在上述列表中的2-4只股票,做简要的专业分析:为什么热、有没有基本面支撑。

格式要求:
- 全程对话体,每段发言前用 [{HOST_A}] 或 [{HOST_B}] 标注,例如:
  [{HOST_A}] 今天我们先看看……
  [{HOST_B}] 对,这个我也注意到了……
- 整体大约2000-3000字
- 把最终完整对话稿放在 <script> 和 </script> 标签之间,
  标签外不要有任何其他内容(不要输出"我先搜索一下"之类的过程性文字)

现在开始。"""


def extract_script(response):
    full_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    if "<script>" in full_text and "</script>" in full_text:
        start = full_text.index("<script>") + len("<script>")
        end = full_text.index("</script>")
        return full_text[start:end].strip()
    return full_text.strip()


def main():
    core_list = load_core_list()
    today_str = date.today().strftime("%Y年%m月%d日")

    print("正在获取核心持仓当日数据...")
    data_table = build_data_table(core_list)
    print(data_table)

    prompt = build_prompt(data_table, today_str)

    print("\n正在调用Claude生成播客脚本(含网络搜索,可能需要1-2分钟)...")
    client = Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=12000,
        tools=[
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    script = extract_script(response)

    print("\n===== 生成的播客脚本 =====\n")
    print(script)
    print("\n===========================\n")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# {today_str} 播客脚本\n\n{script}\n")

    print(f"已写入 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
