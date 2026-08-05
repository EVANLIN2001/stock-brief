#!/usr/bin/env python3
"""把資料 JSON 與人工註記渲染成單檔 HTML 儀表板。

用法：
    python3 scripts/build_dashboard.py --tw data_tw.json --notes notes.json \
        --out /mnt/user-data/outputs/盤後戰報_20260805_台股.html --session tw

刻意不用任何 CDN／外部字型／JS 套件：這份檔案要能離線開、能寄給別人、
能存成封存檔，三年後打開還是長一樣。所有圖表都是伺服器端算好的 inline SVG。

配色沿用台股慣例「紅漲綠跌」，美股面板也一致，因為讀的人是台灣人，
同一份報告裡兩套顏色語言會讀錯。頁尾會註明這件事。
"""
import argparse
import html
import json
import os
from datetime import datetime

# ── 設計 token：黃光室（曝光區打琥珀光，因為光阻對藍紫光敏感）─────────────
CSS = """
:root{
  --fab:#14161C; --panel:#1B1E26; --panel2:#20242E; --line:#2C313D;
  --litho:#F5B944; --copper:#C9743E;
  --wafer:#E9ECF2; --silicon:#8B93A4; --dim:#5E6675;
  --up:#F04A45; --down:#17A67B;
  --mono:ui-monospace,"SF Mono","JetBrains Mono","Roboto Mono",Menlo,Consolas,monospace;
  --sans:"Noto Sans TC","PingFang TC","Microsoft JhengHei","Helvetica Neue",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--fab);color:var(--wafer);font-family:var(--sans);
  font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px 60px}
a{color:var(--litho);text-decoration:none;border-bottom:1px solid rgba(245,185,68,.28)}
a:hover{border-bottom-color:var(--litho)}
:focus-visible{outline:2px solid var(--litho);outline-offset:2px}

/* 標頭：一條琥珀細線 + 場次標記，像機台面板的狀態列 */
.masthead{border-top:2px solid var(--litho);padding-top:14px;margin-bottom:26px}
.eyebrow{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;
  font-family:var(--mono);font-size:11px;letter-spacing:.18em;color:var(--litho);
  text-transform:uppercase}
.eyebrow .sep{color:var(--dim)}
h1{font-size:27px;font-weight:700;letter-spacing:-.01em;margin:8px 0 6px}
.lede{color:var(--silicon);font-size:15.5px;margin:0;max-width:64ch}

/* 參考行情：一排小刻度 */
.ticker{display:flex;flex-wrap:wrap;gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:22px 0 30px}
.tick{flex:1 1 120px;background:var(--panel);padding:9px 12px}
.tick .n{font-size:11px;color:var(--silicon);letter-spacing:.04em}
.tick .v{font-family:var(--mono);font-size:15px;font-weight:600;margin-top:2px}
.tick .c{font-family:var(--mono);font-size:11.5px}

/* 個股卡 */
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  margin-bottom:22px;overflow:hidden}
.card-hd{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;
  justify-content:space-between;padding:18px 20px 14px;
  border-bottom:1px solid var(--line)}
.sym{display:flex;align-items:baseline;gap:10px}
.sym .code{font-family:var(--mono);font-size:12px;color:var(--litho);
  letter-spacing:.1em;border:1px solid rgba(245,185,68,.35);border-radius:3px;
  padding:1px 6px}
.sym .nm{font-size:19px;font-weight:700}
.sym .mk{font-size:11px;color:var(--dim)}
.px{text-align:right;font-family:var(--mono);line-height:1.25}
.px .p{font-size:30px;font-weight:700;letter-spacing:-.02em}
.px .d{font-size:14px}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--silicon)}

.body{padding:18px 20px 20px}
.sec{margin-top:22px}
.sec:first-child{margin-top:0}
.sec-h{font-family:var(--mono);font-size:11px;letter-spacing:.16em;
  color:var(--litho);text-transform:uppercase;margin:0 0 10px;
  display:flex;align-items:center;gap:10px}
.sec-h::after{content:"";flex:1;height:1px;background:var(--line)}

/* 技術面數據格 */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden}
.cell{background:var(--panel2);padding:8px 10px}
.cell .k{font-size:10.5px;color:var(--silicon);letter-spacing:.03em}
.cell .v{font-family:var(--mono);font-size:14px;font-weight:600;margin-top:1px}

/* 新聞 */
.news{list-style:none;margin:0;padding:0}
.news li{padding:11px 0;border-bottom:1px dashed var(--line)}
.news li:last-child{border-bottom:0;padding-bottom:0}
.news .t{font-weight:600;font-size:15px}
.news .s{color:var(--silicon);font-size:13.5px;margin-top:3px}
.news .m{font-family:var(--mono);font-size:10.5px;color:var(--dim);
  letter-spacing:.05em;margin-top:4px}

/* 趨勢觀察：靠左一條銅色標線 */
.trend{border-left:2px solid var(--copper);padding:2px 0 2px 14px}
.stance{display:inline-block;font-family:var(--mono);font-size:11px;
  letter-spacing:.1em;padding:2px 8px;border-radius:3px;margin-bottom:8px;
  background:rgba(201,116,62,.14);color:var(--copper);
  border:1px solid rgba(201,116,62,.35)}
.trend ul{margin:6px 0 0;padding-left:18px;color:var(--silicon);font-size:14px}
.trend li{margin:3px 0}
.lv{display:flex;gap:20px;flex-wrap:wrap;font-family:var(--mono);font-size:13px;
  margin-top:10px;color:var(--silicon)}
.lv b{color:var(--wafer);font-weight:600}

.note{background:var(--panel2);border:1px solid var(--line);border-left:2px solid var(--litho);
  border-radius:0 6px 6px 0;padding:11px 14px;font-size:13.5px;color:var(--silicon)}
.warn{color:var(--copper)}

footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
  font-size:12px;color:var(--dim);line-height:1.8}
footer .dis{color:var(--silicon);margin-top:10px;padding:10px 12px;
  background:var(--panel);border-radius:6px;border:1px solid var(--line)}
svg{display:block;max-width:100%;height:auto}
@media(max-width:600px){
  .wrap{padding:20px 14px 44px} h1{font-size:22px}
  .px .p{font-size:25px} .card-hd{gap:8px}
  .grid{grid-template-columns:repeat(auto-fill,minmax(92px,1fr))}
}
@media(prefers-reduced-motion:no-preference){
  .card{animation:rise .4s ease both}
  @keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
}
@media print{body{background:#fff;color:#111}.card{break-inside:avoid}}
"""


# ────────────────────────────────────────────────────────── 小工具
def esc(x):
    return html.escape(str(x if x is not None else ""))


def fnum(v, dp=2, sign=False):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return esc(v)
    s = f"{v:,.{dp}f}"
    return f"+{s}" if sign and v > 0 else s


def cls(v):
    """台股慣例：紅漲、綠跌。"""
    if v is None:
        return "flat"
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def big(v):
    if v is None:
        return "—"
    v = float(v)
    for div, suf in ((1e8, "億"), (1e4, "萬")):
        if abs(v) >= div:
            return f"{v / div:,.2f}{suf}"
    return f"{v:,.0f}"


# ────────────────────────────────────────────────── SVG：走勢線
def sparkline(hist, w=560, h=104):
    """60 日收盤走勢。淡色 MA20 影子 + 主線 + 末點標記，像量測儀的軌跡。"""
    pts = [p for p in (hist or []) if p.get("c") is not None]
    if len(pts) < 3:
        return ""
    cs = [p["c"] for p in pts]
    lo, hi = min(cs), max(cs)
    rng = (hi - lo) or 1
    pad = 16
    iw, ih = w - pad * 2, h - pad * 2

    def xy(i, c):
        return (pad + i / (len(cs) - 1) * iw, pad + (1 - (c - lo) / rng) * ih)

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, c) for i, c in enumerate(cs)))
    # MA20 影子
    ma = []
    for i in range(len(cs)):
        if i >= 19:
            ma.append((i, sum(cs[i - 19:i + 1]) / 20))
    ma_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in ma))
    up = cs[-1] >= cs[0]
    col = "var(--up)" if up else "var(--down)"
    lx, ly = xy(len(cs) - 1, cs[-1])
    grid = "".join(
        f'<line x1="{pad}" y1="{pad + ih * f:.1f}" x2="{w - pad}" y2="{pad + ih * f:.1f}" '
        f'stroke="var(--line)" stroke-width="1"/>' for f in (0, .5, 1))
    return f'''<svg viewBox="0 0 {w} {h}" role="img" aria-label="近 60 個交易日收盤走勢">
{grid}
<polyline points="{ma_line}" fill="none" stroke="var(--dim)" stroke-width="1"
  stroke-dasharray="3 3" opacity=".75"/>
<polyline points="{line}" fill="none" stroke="{col}" stroke-width="1.8"
  stroke-linejoin="round" stroke-linecap="round"/>
<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.4" fill="{col}"/>
<circle cx="{lx:.1f}" cy="{ly:.1f}" r="6.5" fill="none" stroke="{col}" opacity=".35"/>
<text x="{pad}" y="{pad - 5}" fill="var(--dim)" font-size="10"
  font-family="var(--mono)">{fnum(hi)}</text>
<text x="{pad}" y="{h - 4}" fill="var(--dim)" font-size="10"
  font-family="var(--mono)">{fnum(lo)}</text>
<text x="{w - pad}" y="{h - 4}" fill="var(--dim)" font-size="10" text-anchor="end"
  font-family="var(--mono)">近 60 交易日 · 虛線為 MA20</text>
</svg>'''


# ─────────────────────────── SVG：三大法人籌碼流向（本報告的視覺主軸）
def chipflow(chips, w=560):
    """以零軸為中心的雙向長條。左負右正，刻度像量測尺，一眼看出誰在買誰在賣。"""
    if not chips:
        return ""
    rows = [("外資", chips.get("foreign_net")), ("投信", chips.get("trust_net")),
            ("自營商", chips.get("dealer_net"))]
    rows = [(n, v) for n, v in rows if v is not None]
    if not rows:
        return ""
    total = chips.get("total_net")
    mx = max([abs(v) for _, v in rows] + [1])
    rh, gap, top = 26, 12, 22
    h = top + len(rows) * (rh + gap) + 26
    mid = w / 2
    half = w / 2 - 62

    ticks = ""
    for f in (-1, -.5, 0, .5, 1):
        x = mid + f * half
        ticks += (f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{h - 22}" '
                  f'stroke="{"var(--litho)" if f == 0 else "var(--line)"}" '
                  f'stroke-width="{1.2 if f == 0 else 1}" '
                  f'{"" if f == 0 else 'stroke-dasharray="2 4"'}/>')
        ticks += (f'<text x="{x:.1f}" y="{h - 8}" fill="var(--dim)" font-size="9.5" '
                  f'text-anchor="middle" font-family="var(--mono)">'
                  f'{"0" if f == 0 else fnum(abs(f) * mx, 0)}</text>')

    bars = ""
    for i, (name, v) in enumerate(rows):
        y = top + i * (rh + gap)
        bw = abs(v) / mx * half
        x = mid if v >= 0 else mid - bw
        col = "var(--up)" if v > 0 else ("var(--down)" if v < 0 else "var(--dim)")
        lab_x, anchor = (mid + bw + 8, "start") if v >= 0 else (mid - bw - 8, "end")
        bars += f'''
<text x="6" y="{y + rh / 2 + 4:.0f}" fill="var(--silicon)" font-size="12">{esc(name)}</text>
<rect x="{x:.1f}" y="{y}" width="{max(bw, 1.5):.1f}" height="{rh}" fill="{col}" opacity=".85" rx="1.5"/>
<text x="{lab_x:.1f}" y="{y + rh / 2 + 4:.0f}" fill="{col}" font-size="12" font-weight="600"
  text-anchor="{anchor}" font-family="var(--mono)">{fnum(v, 0, True)}</text>'''

    tcol = "var(--up)" if (total or 0) > 0 else ("var(--down)" if (total or 0) < 0 else "var(--dim)")
    tot = (f'<text x="{w - 4}" y="14" fill="{tcol}" font-size="11.5" text-anchor="end" '
           f'font-family="var(--mono)">合計 {fnum(total, 0, True)} 張</text>') if total is not None else ""
    return (f'<svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="三大法人買賣超，單位張">{ticks}{bars}{tot}'
            f'<text x="6" y="14" fill="var(--dim)" font-size="10.5" '
            f'font-family="var(--mono)">單位：張（賣超 ← | → 買超）</text></svg>')


# ────────────────────────────────────────────────────────── 區塊組裝
def cell(k, v):
    return f'<div class="cell"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'


def tech_grid(t):
    if not t:
        return ""
    c = []
    c.append(cell("均線位置", f'<span style="font-size:12.5px">{esc(t.get("ma_alignment", "—"))}</span>'))
    for k, lbl in (("ma5", "MA5"), ("ma20", "MA20"), ("ma60", "MA60")):
        if t.get(k) is not None:
            d = "up" if t.get("close", 0) > t[k] else "down"
            c.append(cell(lbl, f'<span class="{d}">{fnum(t[k])}</span>'))
    if t.get("bias20") is not None:
        c.append(cell("20日乖離", f'<span class="{cls(t["bias20"])}">{fnum(t["bias20"], 2, True)}%</span>'))
    if t.get("rsi14") is not None:
        tag = "（過熱）" if t["rsi14"] >= 70 else ("（超賣）" if t["rsi14"] <= 30 else "")
        c.append(cell("RSI 14", f'{fnum(t["rsi14"], 1)}<span style="font-size:10px;color:var(--dim)">{tag}</span>'))
    if t.get("k9") is not None:
        x = "K>D" if t["k9"] > (t.get("d9") or 0) else "K<D"
        c.append(cell("KD (9)", f'{fnum(t["k9"], 1)} / {fnum(t.get("d9"), 1)}'
                                f'<span style="font-size:10px;color:var(--dim)"> {x}</span>'))
    if t.get("osc") is not None:
        c.append(cell("MACD 柱", f'<span class="{cls(t["osc"])}">{fnum(t["osc"], 2, True)}</span>'))
    if t.get("vol_ratio") is not None:
        c.append(cell("量能 / 5日均", f'{fnum(t["vol_ratio"], 2)}x'))
    if t.get("high52") is not None:
        c.append(cell("52週高 / 低", f'<span style="font-size:12px">{fnum(t["high52"], 1)} / {fnum(t.get("low52"), 1)}</span>'))
    if t.get("pct_from_high52") is not None:
        c.append(cell("距 52 週高", f'<span class="{cls(t["pct_from_high52"])}">{fnum(t["pct_from_high52"], 1, True)}%</span>'))
    return f'<div class="grid">{"".join(c)}</div>'


def news_block(items):
    if not items:
        return ('<div class="note">今天沒有找到與這檔直接相關的重要新聞。'
                '沒消息不代表沒事，只代表公開資訊面今天安靜。</div>')
    li = ""
    for n in items:
        t = esc(n.get("title", ""))
        if n.get("url"):
            t = f'<a href="{esc(n["url"])}" target="_blank" rel="noopener">{t}</a>'
        meta = " · ".join(x for x in (esc(n.get("source")), esc(n.get("date"))) if x)
        li += (f'<li><div class="t">{t}</div>'
               f'<div class="s">{esc(n.get("summary", ""))}</div>'
               f'<div class="m">{meta}</div></li>')
    return f'<ul class="news">{li}</ul>'


def trend_block(tr):
    if not tr:
        return ""
    out = ""
    if tr.get("stance"):
        out += f'<span class="stance">{esc(tr["stance"])}</span>'
    if tr.get("signals"):
        out += "<ul>" + "".join(f"<li>{esc(s)}</li>" for s in tr["signals"]) + "</ul>"
    lv = []
    if tr.get("support"):
        lv.append(f'支撐 <b>{esc(tr["support"])}</b>')
    if tr.get("resistance"):
        lv.append(f'壓力 <b>{esc(tr["resistance"])}</b>')
    if tr.get("analyst"):
        lv.append(f'分析師目標價 <b>{esc(tr["analyst"])}</b>')
    if lv:
        out += f'<div class="lv">{"".join(f"<span>{x}</span>" for x in lv)}</div>'
    if tr.get("watch"):
        out += f'<div class="note" style="margin-top:12px">接下來看：{esc(tr["watch"])}</div>'
    return f'<div class="trend">{out}</div>'


def stock_card(s, note, is_tw):
    r = s.get("resolved") or {}
    t = s.get("technical") or {}
    code = s.get("code") or s.get("symbol", "")
    mk = ("上市" if s.get("market") == "TWSE" else "上櫃") if is_tw else "美股"
    cp = r.get("change_pct")
    arrow = "▲" if (cp or 0) > 0 else ("▼" if (cp or 0) < 0 else "—")

    secs = []
    if s.get("history"):
        secs.append(f'<div class="sec"><h3 class="sec-h">價格走勢</h3>{sparkline(s["history"])}</div>')
    if is_tw and s.get("chips"):
        cd = s["chips"].get("date")
        extra = f'<span style="color:var(--dim);font-size:10px">（{esc(cd)}）</span>' if cd else ""
        secs.append(f'<div class="sec"><h3 class="sec-h">三大法人買賣超 {extra}</h3>'
                    f'{chipflow(s["chips"])}</div>')
    if is_tw and s.get("margin"):
        m = s["margin"]
        cs = [cell("融資餘額", f'{fnum(m.get("margin_balance"), 0)} 張'),
              cell("融資增減", f'<span class="{cls(m.get("margin_change"))}">'
                             f'{fnum(m.get("margin_change"), 0, True)}</span>'),
              cell("融券餘額", f'{fnum(m.get("short_balance"), 0)} 張'),
              cell("融券增減", f'<span class="{cls(m.get("short_change"))}">'
                             f'{fnum(m.get("short_change"), 0, True)}</span>')]
        if m.get("margin_util") is not None:
            cs.append(cell("資使用率", f'{fnum(m["margin_util"], 2)}%'))
        secs.append(f'<div class="sec"><h3 class="sec-h">信用交易</h3>'
                    f'<div class="grid">{"".join(cs)}</div></div>')
    secs.append(f'<div class="sec"><h3 class="sec-h">技術面</h3>{tech_grid(t)}</div>')
    secs.append(f'<div class="sec"><h3 class="sec-h">今日消息</h3>{news_block(note.get("news"))}</div>')
    if note.get("trend"):
        secs.append(f'<div class="sec"><h3 class="sec-h">趨勢觀察</h3>{trend_block(note["trend"])}</div>')

    vol = r.get("volume_shares")
    vtxt = f'{fnum((vol or 0) / 1000, 0)} 張' if is_tw and vol else (big(vol) if vol else "—")
    sub = (f'開 {fnum(r.get("open"))} · 高 {fnum(r.get("high"))} · 低 {fnum(r.get("low"))} · '
           f'量 {vtxt}')
    return f'''<article class="card">
<div class="card-hd">
  <div class="sym"><span class="code">{esc(code)}</span>
    <span class="nm">{esc(s.get("name", ""))}</span><span class="mk">{mk}</span></div>
  <div class="px"><div class="p {cls(cp)}">{fnum(r.get("close"))}</div>
    <div class="d {cls(cp)}">{arrow} {fnum(r.get("change"), 2, True)}（{fnum(cp, 2, True)}%）</div></div>
</div>
<div class="body">
  <div style="font-family:var(--mono);font-size:12px;color:var(--dim);margin-bottom:14px">{sub}</div>
  {"".join(secs)}
</div></article>'''


def ticker_row(ctx):
    if not ctx:
        return ""
    ts = ""
    for c in ctx:
        ts += (f'<div class="tick"><div class="n">{esc(c["name"])}</div>'
               f'<div class="v {cls(c.get("change_pct"))}">{fnum(c.get("close"))}</div>'
               f'<div class="c {cls(c.get("change_pct"))}">{fnum(c.get("change_pct"), 2, True)}%'
               f'<span style="color:var(--dim)"> {esc(c.get("date", ""))}</span></div></div>')
    return f'<div class="ticker">{ts}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tw"), ap.add_argument("--us"), ap.add_argument("--notes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--session", default="both", choices=["tw", "us", "both"])
    a = ap.parse_args()

    load = lambda p: json.load(open(p, encoding="utf-8")) if p and os.path.exists(p) else None
    tw, us, notes = load(a.tw), load(a.us), load(a.notes) or {}
    per = notes.get("stocks", {})

    label = {"tw": "台股場次", "us": "美股場次", "both": "台股 + 美股"}[a.session]
    dates = [x["trading_date"] for x in (tw, us) if x and x.get("trading_date")]
    tdate = " / ".join(sorted(set(dates))) or datetime.now().strftime("%Y-%m-%d")
    gen = (tw or us or {}).get("generated_at", "")

    body = ""
    for src, is_tw, hd in ((tw, True, "台股"), (us, False, "美股")):
        if not src or not src.get("stocks"):
            continue
        body += ticker_row(src.get("context"))
        for s in src["stocks"]:
            key = s.get("code") or s.get("symbol")
            body += stock_card(s, per.get(key, {}), is_tw)

    warns = [w for x in (tw, us) if x for w in x.get("warnings", [])]
    wblock = ("<div class='note' style='margin-bottom:22px'><b class='warn'>資料狀態</b><br>"
              + "<br>".join(esc(w) for w in warns) + "</div>") if warns else ""

    macro = f'<p class="lede">{esc(notes.get("macro"))}</p>' if notes.get("macro") else ""
    out = f'''<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>盤後戰報 {esc(tdate)}｜{esc(label)}</title><style>{CSS}</style></head><body>
<div class="wrap">
<header class="masthead">
  <div class="eyebrow"><span>盤後戰報</span><span class="sep">/</span><span>{esc(label)}</span>
    <span class="sep">/</span><span>{esc(tdate)}</span></div>
  <h1>{esc(notes.get("headline") or "今日持股動態")}</h1>
  {macro}
</header>
{wblock}
{body}
<footer>
  資料來源：台灣證券交易所 OpenAPI、證交所盤後資訊、櫃買中心 OpenAPI、Yahoo Finance。
  技術指標由收盤價自行計算（MA／RSI 14／KD 9,3,3／MACD 12,26,9）。
  新聞與分析師觀點由網路搜尋整理，已改寫摘要，詳情請點連結看原文。<br>
  漲跌色彩統一採台股慣例：<span class="up">紅色為漲</span>、<span class="down">綠色為跌</span>，
  美股面板亦同，避免同一份報告出現兩套顏色語言。<br>
  產出時間：{esc(gen)}（台北時間）
  <div class="dis">這份報告是公開資訊的整理與技術指標的計算結果，不是投資建議，也沒有預測價格。
  技術訊號描述的是「目前的狀態」而非「未來的結果」，籌碼與新聞都可能在下一個交易日反轉。
  任何買賣決定請自行判斷並承擔風險。</div>
</footer>
</div></body></html>'''

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"寫出 {a.out}（{len(out) / 1024:.1f} KB）")


if __name__ == "__main__":
    main()
