#!/usr/bin/env python3
"""抓美股盤後資料：Yahoo Finance 行情 + 技術面 + 大盤／族群對照。

用法：
    python3 scripts/fetch_us.py --out /home/claude/data_us.json
    python3 scripts/fetch_us.py --symbols MU,NVDA --out ...

美股沒有台股那種三大法人公開日報，籌碼面資訊（機構持股、13F、空單比）
更新頻率是季或雙週，不適合當每日指標。所以這裡只出行情與技術面，
分析師目標價與法人動向留給 SKILL.md 指示用網路搜尋補，並標註資料日期。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import now_tpe, quote_line, technicals, yahoo_chart  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--watchlist", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "watchlist.json"))
    a = ap.parse_args()

    wl = json.load(open(a.watchlist, encoding="utf-8"))
    targets = wl["us"]
    if a.symbols:
        want = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
        known = {t["symbol"].upper(): t for t in targets}
        targets = [known.get(s, {"symbol": s, "name": s}) for s in want]

    warn, stocks = [], []
    for t in targets:
        rec = {"symbol": t["symbol"], "name": t.get("name", t["symbol"])}
        try:
            ch = yahoo_chart(t["symbol"], rng="1y")
            bars = ch["bars"]
            tech = technicals(bars)
            lb = bars[-1]
            rec["currency"] = ch.get("currency")
            rec["market_state"] = ch.get("market_state")
            rec["technical"] = tech
            src = ch.get("source", "Yahoo Finance")
            rec["resolved"] = {
                "date": lb["date"], "open": lb["open"], "high": lb["high"], "low": lb["low"],
                "close": tech.get("close"), "change": tech.get("change"),
                "change_pct": tech.get("change_pct"), "volume_shares": lb["volume"],
                "source": src,
            }
            if src != "Yahoo Finance":
                warn.append(f"{t['symbol']} Yahoo 不可用，行情改用{src}")
            m = ch.get("meta", {})
            # 盤前／盤後報價（有才給，沒有不要硬湊）
            for k, label in (("preMarketPrice", "pre"), ("postMarketPrice", "post")):
                if m.get(k):
                    rec.setdefault("extended", {})[label] = round(float(m[k]), 2)
            rec["history"] = [{"d": b["date"], "c": round(b["close"], 2), "v": b["volume"]}
                              for b in bars[-60:]]
        except Exception as e:  # noqa: BLE001
            warn.append(f"{t['symbol']} 行情抓取失敗（主要與備援來源皆失敗）：{e}")
        stocks.append(rec)

    ctx = [q for q in (quote_line(x["symbol"], x["name"]) for x in wl.get("context_us", [])) if q]
    dates = [s.get("resolved", {}).get("date") for s in stocks if s.get("resolved")]
    payload = {"market": "us", "generated_at": now_tpe(),
               "trading_date": max(dates) if dates else None,
               "stocks": stocks, "context": ctx, "warnings": warn}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"寫出 {a.out}｜交易日 {payload['trading_date']}｜標的 {len(stocks)}｜警告 {len(warn)}")
    for w in warn:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
