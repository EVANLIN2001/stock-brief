#!/usr/bin/env python3
"""抓台股盤後資料：官方籌碼（三大法人、融資融券）＋ Yahoo 歷史行情算技術面。

用法：
    python3 scripts/fetch_tw.py --out /home/claude/data_tw.json
    python3 scripts/fetch_tw.py --codes 2330,5425 --out ...

設計原則：任何一個來源掛掉都只記進 warnings，其他資料照常產出。
盤後資料有發布時間差（證交所約 15:00-16:00、櫃買約 15:30 之後），
所以每一段資料都會標自己的 data_date，讓報告能誠實講出「這是哪一天的數字」。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (TPE, http_json, norm_keys, now_tpe, num, quote_line,  # noqa: E402
                    roc_to_iso, technicals, yahoo_chart)

TWSE_DAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_MARGIN = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
TWSE_PER = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json"
TPEX_QUOTE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
TPEX_3INSTI = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TPEX_MARGIN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"

LOT = 1000  # 張 = 1000 股


def _find(rows, key, code):
    for r in rows:
        if str(r.get(key, "")).strip() == code:
            return r
    return None


def fetch_twse(codes, warn):
    """上市：日成交、三大法人(T86)、融資融券、本益比。"""
    out = {c: {} for c in codes}
    day_date = None
    try:
        rows = http_json(TWSE_DAY)
        for c in codes:
            r = _find(rows, "Code", c)
            if not r:
                continue
            day_date = roc_to_iso(r.get("Date"))
            out[c]["quote"] = {
                "date": day_date, "name": r.get("Name", "").strip(),
                "open": num(r.get("OpeningPrice")), "high": num(r.get("HighestPrice")),
                "low": num(r.get("LowestPrice")), "close": num(r.get("ClosingPrice")),
                "change": num(r.get("Change")),
                "volume_shares": num(r.get("TradeVolume")),
                "turnover": num(r.get("TradeValue")),
                "transactions": num(r.get("Transaction")),
            }
    except Exception as e:  # noqa: BLE001
        warn.append(f"證交所日成交抓取失敗：{e}")

    # 證交所各檔案發布時間不一致（STOCK_DAY_ALL 有時比 T86 慢一天），
    # 所以從「今天」往回試，抓到第一個有資料的交易日為準，避免誤用舊籌碼。
    today = datetime.now(TPE)
    cands = [today.strftime("%Y%m%d")]
    if day_date:
        cands.append(day_date.replace("-", ""))
    for k in range(1, 6):
        cands.append((today - timedelta(days=k)).strftime("%Y%m%d"))
    seen, ymd, d = set(), None, None
    for cand in cands:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            r = http_json(TWSE_T86.format(ymd=cand), tries=1, timeout=25)
        except Exception:  # noqa: BLE001
            continue
        if r.get("stat") == "OK" and r.get("data"):
            ymd, d = cand, r
            break
    try:
        if d is None:
            raise RuntimeError("近 5 個日期皆無三大法人資料（可能連假或尚未發布）")
        if True:
            t86_date = roc_to_iso(d.get("date", ymd)) if len(str(d.get("date", ""))) == 7 else \
                f"{str(d.get('date'))[:4]}-{str(d.get('date'))[4:6]}-{str(d.get('date'))[6:8]}"
            for c in codes:
                r = None
                for row in d.get("data", []):
                    if str(row[0]).strip() == c:
                        r = row
                        break
                if not r:
                    continue
                fo = num(r[4], 0) + num(r[7], 0)  # 外陸資 + 外資自營商
                out[c]["chips"] = {
                    "date": t86_date,
                    "foreign_net": fo / LOT,
                    "trust_net": num(r[10], 0) / LOT,
                    "dealer_net": num(r[11], 0) / LOT,
                    "total_net": num(r[18], 0) / LOT,
                    "unit": "張",
                }
    except Exception as e:  # noqa: BLE001
        warn.append(f"證交所三大法人抓取失敗：{e}")

    try:
        rows = http_json(TWSE_MARGIN)
        for c in codes:
            r = _find(rows, "股票代號", c)
            if r:
                out[c]["margin"] = {
                    "margin_balance": num(r.get("融資今日餘額")),
                    "margin_change": (num(r.get("融資今日餘額"), 0) - num(r.get("融資前日餘額"), 0)),
                    "short_balance": num(r.get("融券今日餘額")),
                    "short_change": (num(r.get("融券今日餘額"), 0) - num(r.get("融券前日餘額"), 0)),
                    "unit": "張",
                    "date": None,
                    "note": "證交所此檔未附日期欄位，取最新發布值，可能落後收盤一日",
                }
    except Exception as e:  # noqa: BLE001
        warn.append(f"證交所融資融券抓取失敗：{e}")

    try:
        rows = http_json(TWSE_PER)
        for c in codes:
            r = _find(rows, "Code", c)
            if r:
                out[c]["valuation"] = {"pe": num(r.get("PEratio")),
                                       "yield": num(r.get("DividendYield")),
                                       "pb": num(r.get("PBratio"))}
    except Exception as e:  # noqa: BLE001
        warn.append(f"證交所本益比抓取失敗：{e}")
    return out


def fetch_tpex(codes, warn):
    """上櫃：日成交、三大法人、融資融券。欄位名有多餘空白，一律 norm_keys 後比對。"""
    out = {c: {} for c in codes}
    try:
        rows = [norm_keys(r) for r in http_json(TPEX_QUOTE)]
        for c in codes:
            r = _find(rows, "SecuritiesCompanyCode", c)
            if not r:
                continue
            out[c]["quote"] = {
                "date": roc_to_iso(r.get("Date")), "name": (r.get("CompanyName") or "").strip(),
                "open": num(r.get("Open")), "high": num(r.get("High")), "low": num(r.get("Low")),
                "close": num(r.get("Close")), "change": num(r.get("Change")),
                "volume_shares": num(r.get("TradingShares")),
                "turnover": num(r.get("TransactionAmount")),
                "transactions": num(r.get("TransactionNumber")),
            }
    except Exception as e:  # noqa: BLE001
        warn.append(f"櫃買日成交抓取失敗：{e}")

    try:
        rows = [norm_keys(r) for r in http_json(TPEX_3INSTI)]
        for c in codes:
            r = _find(rows, "SecuritiesCompanyCode", c)
            if not r:
                continue
            fo = num(r.get("ForeignInvestorsIncludeMainlandAreaInvestors-Difference"), 0)
            tr = num(r.get("SecuritiesInvestmentTrustCompanies-Difference"), 0)
            de = num(r.get("Dealers-Difference"), 0)
            out[c]["chips"] = {
                "date": roc_to_iso(r.get("Date")),
                "foreign_net": fo / LOT, "trust_net": tr / LOT, "dealer_net": de / LOT,
                "total_net": num(r.get("TotalDifference"), fo + tr + de) / LOT, "unit": "張",
            }
    except Exception as e:  # noqa: BLE001
        warn.append(f"櫃買三大法人抓取失敗：{e}")

    try:
        rows = [norm_keys(r) for r in http_json(TPEX_MARGIN)]
        for c in codes:
            r = _find(rows, "SecuritiesCompanyCode", c)
            if not r:
                continue
            mb, mp = num(r.get("MarginPurchaseBalance")), num(r.get("MarginPurchaseBalancePreviousDay"))
            sb, sp = num(r.get("ShortSaleBalance")), num(r.get("ShortSaleBalancePreviousDay"))
            out[c]["margin"] = {
                "date": roc_to_iso(r.get("Date")),
                "margin_balance": mb,
                "margin_change": (mb - mp) if (mb is not None and mp is not None) else None,
                "margin_util": num(r.get("MarginPurchaseUtilizationRate")),
                "short_balance": sb,
                "short_change": (sb - sp) if (sb is not None and sp is not None) else None,
                "unit": "張",
            }
    except Exception as e:  # noqa: BLE001
        warn.append(f"櫃買融資融券抓取失敗：{e}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--codes", default="")
    ap.add_argument("--watchlist", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "watchlist.json"))
    a = ap.parse_args()

    wl = json.load(open(a.watchlist, encoding="utf-8"))
    targets = wl["tw"]
    if a.codes:
        want = [c.strip() for c in a.codes.split(",") if c.strip()]
        targets = [t for t in targets if t["code"] in want]

    warn = []
    twse_codes = [t["code"] for t in targets if t.get("market") == "TWSE"]
    tpex_codes = [t["code"] for t in targets if t.get("market") == "TPEx"]
    off = {}
    if twse_codes:
        off.update(fetch_twse(twse_codes, warn))
    if tpex_codes:
        off.update(fetch_tpex(tpex_codes, warn))

    stocks = []
    for t in targets:
        c = t["code"]
        rec = {"code": c, "name": t["name"], "market": t.get("market"), "yahoo": t["yahoo"]}
        rec.update(off.get(c, {}))
        try:
            ch = yahoo_chart(t["yahoo"], rng="1y")
            bars = ch["bars"]
            rec["technical"] = technicals(bars)
            rec["history"] = [{"d": b["date"], "c": round(b["close"], 2), "v": b["volume"]}
                              for b in bars[-60:]]
            # 官方收盤與 Yahoo 收盤對不起來時要講出來，通常代表某一邊還沒更新
            # 決定報告要用哪一份收盤：官方檔權威但常慢一拍，Yahoo 快但非官方。
            # 誰的日期新就用誰，並把來源寫進 resolved，報告才能誠實標註。
            q = rec.get("quote", {})
            t, lb = rec["technical"], bars[-1]
            hist_src = ch.get("source", "Yahoo Finance")
            if hist_src != "Yahoo Finance":
                warn.append(f"{c} Yahoo 不可用，技術面改用{hist_src}計算")
            if q.get("date") and q["date"] >= lb["date"]:
                rec["resolved"] = dict(q, source="證交所/櫃買官方",
                                       change_pct=t.get("change_pct"))
            else:
                rec["resolved"] = {
                    "date": lb["date"], "open": lb["open"], "high": lb["high"],
                    "low": lb["low"], "close": t.get("close"), "change": t.get("change"),
                    "change_pct": t.get("change_pct"), "volume_shares": lb["volume"],
                    "source": f"{hist_src}（官方日成交檔尚未更新）",
                }
                if q.get("date"):
                    warn.append(f"{c} 證交所/櫃買日成交檔只到 {q['date']}，"
                                f"價格改用{hist_src} {lb['date']} 收盤")
        except Exception as e:  # noqa: BLE001
            warn.append(f"{c} 歷史行情抓取失敗（主要與備援來源皆失敗）：{e}")
        stocks.append(rec)

    ctx = [q for q in (quote_line(x["symbol"], x["name"]) for x in wl.get("context_tw", [])) if q]

    dates = [s.get("quote", {}).get("date") for s in stocks if s.get("quote", {}).get("date")]
    payload = {
        "market": "tw", "generated_at": now_tpe(),
        "trading_date": max(dates) if dates else None,
        "stocks": stocks, "context": ctx, "warnings": warn,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"寫出 {a.out}｜交易日 {payload['trading_date']}｜標的 {len(stocks)}｜警告 {len(warn)}")
    for w in warn:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
