"""共用工具：HTTP 抓取、Yahoo Finance 行情、技術指標計算。

只用標準函式庫，避免環境缺套件就整個掛掉。
"""
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
TPE = timezone(timedelta(hours=8))
LOT_SHARES = 1000  # 台股 1 張 = 1000 股


def http_json(url, tries=3, timeout=30):
    """抓 JSON。失敗會重試，最後仍失敗則丟出例外讓呼叫端記錄 warning 而非整支腳本中斷。"""
    last = None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失敗 {url} -> {last}")


def num(v, default=None):
    """把 '1,234.5' / '+1.90' / '--' 這類字串轉成數字，轉不動就回 default。"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "---", "X", "N/A", "null"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def norm_keys(d):
    """TPEx 的欄位名稱夾雜多餘空白（例如 ' Foreign...-Total Sell'），統一去空白再比對。"""
    return {"".join(str(k).split()): v for k, v in d.items()}


def roc_to_iso(s):
    """民國日期 1150805 -> 2026-08-05。"""
    s = str(s).strip().replace("/", "")
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911:04d}-{s[3:5]}-{s[5:7]}"
    return s


# ---------------------------------------------------------------- Yahoo 行情

def _yahoo_chart(symbol, rng="1y", interval="1d"):
    """回傳 {symbol, currency, meta, bars:[{date, open, high, low, close, volume}]}。

    注意：meta 裡的 chartPreviousClose 是「range 起點之前」的收盤，不是昨收。
    要算漲跌一律用 bars 最後兩根，才不會出現離譜數字。
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?range={rng}&interval={interval}"
    )
    d = http_json(url)
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError(f"Yahoo 無資料：{symbol}")
    r = res[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        c = q.get("close", [None] * len(ts))[i]
        if c is None:
            continue
        gmtoff = meta.get("gmtoffset", 0) or 0
        bars.append({
            "date": datetime.fromtimestamp(t + gmtoff, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": q.get("open", [None] * len(ts))[i],
            "high": q.get("high", [None] * len(ts))[i],
            "low": q.get("low", [None] * len(ts))[i],
            "close": c,
            "volume": q.get("volume", [None] * len(ts))[i] or 0,
        })
    return {"symbol": meta.get("symbol", symbol), "currency": meta.get("currency"),
            "market_state": meta.get("marketState"), "meta": meta, "bars": bars}


# -------------------------------------------------- 備援行情（Yahoo 掛掉時才走）
#
# Yahoo 會對某些 IP 整段回 429（query1／query2 都擋，連 cookie+crumb 流程也拿不到），
# 一掛掉就等於技術指標全空、美股整個場次失效。所以每一種標的都準備一條官方或
# 免金鑰的替代路徑。實際用了哪一條會寫進回傳值的 source，報告要據實標註。

def _month_firsts(n):
    """最近 n 個月的月初（新到舊）。官方月檔一次給一個月，要靠這個往回撈。"""
    d = datetime.now(TPE).replace(day=1)
    out = []
    for _ in range(n):
        out.append(d)
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def _twse_month_bars(code, ymd):
    """證交所個股月成交檔。欄位：日期,成交股數,成交金額,開盤,最高,最低,收盤,漲跌,筆數。"""
    d = http_json("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                  f"?date={ymd}&stockNo={code}&response=json", tries=2, timeout=25)
    if d.get("stat") != "OK":
        return []
    out = []
    for row in d.get("data") or []:
        c = num(row[6])
        if c is None:
            continue
        out.append({"date": roc_to_iso(row[0]), "open": num(row[3]), "high": num(row[4]),
                    "low": num(row[5]), "close": c, "volume": num(row[1], 0)})
    return out


def _tpex_month_bars(code, ymd):
    """櫃買個股月成交檔。成交量欄位是「張」，乘 1000 換成股才跟 Yahoo 對得起來。"""
    d = http_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
                  f"?code={code}&date={ymd[:4]}/{ymd[4:6]}/01&id=&response=json",
                  tries=2, timeout=25)
    tables = d.get("tables") or []
    if not tables:
        return []
    out = []
    for row in tables[0].get("data") or []:
        c = num(row[6])
        if c is None:
            continue
        out.append({"date": roc_to_iso(row[0]), "open": num(row[3]), "high": num(row[4]),
                    "low": num(row[5]), "close": c, "volume": (num(row[1], 0) or 0) * LOT_SHARES})
    return out


def _twse_index_month_bars(ymd):
    """加權指數月歷史。欄位：日期,開盤,最高,最低,收盤（指數沒有成交量欄位）。"""
    d = http_json("https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
                  f"?date={ymd}&response=json", tries=2, timeout=25)
    if d.get("stat") != "OK":
        return []
    out = []
    for row in d.get("data") or []:
        c = num(row[4])
        if c is None:
            continue
        out.append({"date": roc_to_iso(row[0]), "open": num(row[1]), "high": num(row[2]),
                    "low": num(row[3]), "close": c, "volume": 0})
    return out


def _tw_official_chart(symbol, rng="1y"):
    """用證交所／櫃買官方月檔拼出日線。symbol 形如 2330.TW、5425.TWO、^TWII。"""
    months = 3 if rng in ("1mo", "3mo") else 13
    s = symbol.upper()
    if s == "^TWII":
        fetch, src = (lambda ymd: _twse_index_month_bars(ymd)), "證交所加權指數月歷史"
    else:
        code = symbol.partition(".")[0]
        if s.endswith(".TWO"):
            fetch, src = (lambda ymd: _tpex_month_bars(code, ymd)), "櫃買官方月成交檔"
        else:
            fetch, src = (lambda ymd: _twse_month_bars(code, ymd)), "證交所官方月成交檔"

    bars, seen = [], set()
    for d in _month_firsts(months):
        try:
            got = fetch(d.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            continue  # 單一月份失敗不影響其他月份，缺幾天技術指標仍算得出來
        for b in got:
            if b["date"] not in seen:
                seen.add(b["date"])
                bars.append(b)
        time.sleep(0.3)  # 官方站台不要連續猛打
    if not bars:
        raise RuntimeError(f"官方月檔無資料：{symbol}")
    bars.sort(key=lambda b: b["date"])
    return {"symbol": symbol, "currency": "TWD", "market_state": None,
            "meta": {}, "bars": bars, "source": src}


# stockanalysis.com 只收個股與 ETF，不吃指數代號，所以指數改用貼身 ETF 代理。
# 代理不等於指數本身，source 會標明，報告不可以寫成「費半上漲 X%」。
_US_INDEX_PROXY = {
    "^SOX": ("SOXX", "iShares 半導體 ETF，費半代理"),
    "^IXIC": ("QQQ", "Invesco QQQ，那斯達克代理"),
    "^GSPC": ("SPY", "SPDR S&P 500 ETF，S&P 500 代理"),
    "^DJI": ("DIA", "SPDR 道瓊 ETF，道瓊代理"),
}


def _stockanalysis_chart(symbol, rng="1y"):
    """stockanalysis.com 免金鑰日線。回傳是新到舊，要自己排序。"""
    proxy, note = _US_INDEX_PROXY.get(symbol.upper(), (symbol, None))
    if proxy.startswith("^"):
        raise RuntimeError(f"無對應備援來源：{symbol}")
    r = "5Y" if rng in ("2y", "5y") else "1Y"
    d = http_json(f"https://stockanalysis.com/api/symbol/s/{urllib.parse.quote(proxy.lower())}"
                  f"/history?range={r}&period=Daily", tries=2, timeout=25)
    if d.get("status") != 200 or not d.get("data"):
        raise RuntimeError(f"stockanalysis 無資料：{symbol}")
    bars = []
    for row in d["data"]:
        c = num(row.get("c"))
        if c is None:
            continue
        bars.append({"date": row.get("t"), "open": num(row.get("o")), "high": num(row.get("h")),
                     "low": num(row.get("l")), "close": c, "volume": num(row.get("v"), 0)})
    if not bars:
        raise RuntimeError(f"stockanalysis 無有效 K 棒：{symbol}")
    bars.sort(key=lambda b: b["date"])
    out = {"symbol": symbol, "currency": "USD", "market_state": None, "meta": {}, "bars": bars,
           "source": "stockanalysis.com" + (f"（{note}）" if note else "")}
    if note:
        # 代理 ETF 的「點位」跟指數本身差一個量級（SOXX 五百多 vs 費半六千多），
        # 只把來源寫在 source 不夠，呼叫端會照樣印出看似指數的數字，所以另外標出來。
        out["proxy"] = proxy
    return out


def yahoo_chart(symbol, rng="1y", interval="1d"):
    """行情主入口：先試 Yahoo，掛掉再走備援。

    回傳值一定帶 `source` 欄位標明實際來源——函式名字叫 yahoo_chart 不代表資料來自
    Yahoo，報告要照 source 標，不要憑函式名稱寫來源。
    """
    try:
        d = _yahoo_chart(symbol, rng=rng, interval=interval)
        if d["bars"]:
            d["source"] = "Yahoo Finance"
            return d
        last = RuntimeError("Yahoo 回傳空 K 棒")
    except Exception as e:  # noqa: BLE001
        last = e

    s = symbol.upper()
    if s.endswith(".TW") or s.endswith(".TWO") or s == "^TWII":
        fallback = _tw_official_chart
    elif s.startswith("^") and s not in _US_INDEX_PROXY:
        fallback = None  # 例如 ^TWOII，櫃買指數沒有可用的免金鑰歷史來源
    else:
        fallback = _stockanalysis_chart
    if fallback is None:
        raise RuntimeError(f"抓取失敗 {symbol}（Yahoo：{last}；無備援來源）")
    try:
        return fallback(symbol, rng)
    except Exception as e2:  # noqa: BLE001
        raise RuntimeError(f"抓取失敗 {symbol}（Yahoo：{last}；備援：{e2}）")


def quote_line(symbol, name, rng="3mo"):
    """給大盤/指數用的精簡報價（給儀表板的參考行情列）。"""
    try:
        ch = yahoo_chart(symbol, rng=rng)
        b = ch["bars"]
        if len(b) < 2:
            return None
        last, prev = b[-1]["close"], b[-2]["close"]
        proxy = ch.get("proxy")
        return {"symbol": symbol,
                # 用代理 ETF 時名稱一定要改掉，否則報告會把 ETF 價位當成指數點位寫出去
                "name": f"{name}（{proxy} ETF 代理，非指數點位）" if proxy else name,
                "close": round(last, 2),
                "change": round(last - prev, 2),
                "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
                "date": b[-1]["date"], "source": ch.get("source"), "proxy": proxy}
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------ 技術指標

def _sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ema_series(xs, n):
    if len(xs) < n:
        return []
    k = 2 / (n + 1)
    e = sum(xs[:n]) / n
    out = [e]
    for x in xs[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0)
        losses += max(-ch, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(ch, 0)) / n
        al = (al * (n - 1) + max(-ch, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def _kd(bars, n=9):
    """台股習慣的 KD（9,3,3），K/D 用 1/3 平滑。"""
    if len(bars) < n + 3:
        return None, None
    k = d = 50.0
    for i in range(n - 1, len(bars)):
        win = bars[i - n + 1:i + 1]
        hi = max(b["high"] for b in win if b["high"] is not None)
        lo = min(b["low"] for b in win if b["low"] is not None)
        rsv = 50.0 if hi == lo else (bars[i]["close"] - lo) / (hi - lo) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
    return round(k, 1), round(d, 1)


def _macd(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig:
        return None, None, None
    ef, es = _ema_series(closes, fast), _ema_series(closes, slow)
    ef = ef[len(ef) - len(es):]
    dif = [a - b for a, b in zip(ef, es)]
    macd = _ema_series(dif, sig)
    if not macd:
        return None, None, None
    return round(dif[-1], 3), round(macd[-1], 3), round(dif[-1] - macd[-1], 3)


def technicals(bars):
    """算出一組給人看的技術面數字。資料不足的項目回 None，不要硬掰。"""
    closes = [b["close"] for b in bars if b["close"] is not None]
    vols = [b["volume"] for b in bars if b["volume"] is not None]
    if len(closes) < 2:
        return {}
    last, prev = closes[-1], closes[-2]
    ma20, ma60 = _sma(closes, 20), _sma(closes, 60)
    k, d = _kd(bars)
    dif, macd, osc = _macd(closes)
    win52 = closes[-250:]
    out = {
        "close": round(last, 2),
        "prev_close": round(prev, 2),
        "change": round(last - prev, 2),
        "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
        "ma5": round(_sma(closes, 5), 2) if _sma(closes, 5) else None,
        "ma10": round(_sma(closes, 10), 2) if _sma(closes, 10) else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "bias20": round((last - ma20) / ma20 * 100, 2) if ma20 else None,
        "rsi14": round(_rsi(closes), 1) if _rsi(closes) else None,
        "k9": k, "d9": d, "dif": dif, "macd": macd, "osc": osc,
        "high52": round(max(win52), 2), "low52": round(min(win52), 2),
        "pct_from_high52": round((last - max(win52)) / max(win52) * 100, 2),
        "vol": vols[-1] if vols else None,
        "vol_ma5": round(_sma(vols, 5)) if _sma(vols, 5) else None,
        "vol_ratio": round(vols[-1] / _sma(vols, 5), 2) if vols and _sma(vols, 5) else None,
    }
    # 均線排列：多頭＝價>MA5>MA20>MA60
    if all(out[x] for x in ("ma5", "ma20", "ma60")):
        if last > out["ma5"] > out["ma20"] > out["ma60"]:
            out["ma_alignment"] = "多頭排列"
        elif last < out["ma5"] < out["ma20"] < out["ma60"]:
            out["ma_alignment"] = "空頭排列"
        else:
            out["ma_alignment"] = "均線糾結"
    return out


def now_tpe():
    return datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
