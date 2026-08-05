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

def yahoo_chart(symbol, rng="1y", interval="1d"):
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


def quote_line(symbol, name, rng="3mo"):
    """給大盤/指數用的精簡報價（給儀表板的參考行情列）。"""
    try:
        ch = yahoo_chart(symbol, rng=rng)
        b = ch["bars"]
        if len(b) < 2:
            return None
        last, prev = b[-1]["close"], b[-2]["close"]
        return {"symbol": symbol, "name": name, "close": round(last, 2),
                "change": round(last - prev, 2),
                "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
                "date": b[-1]["date"]}
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
