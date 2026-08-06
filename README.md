# stock-brief

台股／美股盤後戰報。全自動、跑在雲端，電腦關機照跑。

追蹤標的：台積電 2330、台半 5425、美光 MU。
要增刪標的改 `.claude/skills/stock-daily-brief/assets/watchlist.json`，不用動程式。
**改完要 push，下一次執行才會吃到新版本。**

## 架構：為什麼是兩段式

Claude Routine 跑在 Anthropic 雲端，那個環境的 egress proxy **擋掉所有財經網域**——
證交所、櫃買、Yahoo、Stooq、Nasdaq 一律 `CONNECT 403`（proxy 政策拒絕，不是站方限流）。
routine 自己一個位元組的行情都拿不到。

所以拆成兩段，各自做自己能做的事：

```
GitHub Actions（網路不受限）          Claude Routine（能查新聞、會判讀）
台北 15:30 / 05:30                    台北 16:00 / 06:00
  ↓ 跑 fetch_tw.py / fetch_us.py        ↓ 讀 data/*.json（不連外）
  ↓ commit 進 data/                     ↓ WebSearch 查消息面
                                        ↓ 產 HTML + SendUserFile 交付
                                        ↓ 最後訊息寫完整戰報
```

中間留 30 分鐘，是給 GitHub Actions 排程延遲的緩衝。routine 會檢查 `generated_at`
與 `trading_date`，資料不新就在第一行標警告，不會假裝是今天的數字。

## 排程

| 元件 | 台北時間 | Cron (UTC) | ID |
|---|---|---|---|
| GH Actions 台股 | 週一～五 15:30 | `30 7 * * 1-5` | `.github/workflows/fetch-tw.yml` |
| GH Actions 美股 | 週一～五 05:30 | `30 21 * * 1-5` | `.github/workflows/fetch-us.yml` |
| Routine 台股 | 週一～五 16:00 | `0 8 * * 1-5` | `trig_01GgVN5ayfpKq6biKQ7aWW9S` |
| Routine 美股 | 週二～六 06:00 | `0 22 * * 1-5` | `trig_01NREP3f1faZGGqeTUmiT3FA` |

美股排週二到週六，因為對應的是週一到週五的美股交易日。美股夏令 04:00、冬令 05:00
（台北時間）收盤，05:30 抓、06:00 出報告，兩種情況都拿得到完整收盤。

- Routines：<https://claude.ai/code/routines>
- Actions：<https://github.com/EVANLIN2001/stock-brief/actions>

## 結構

```
.claude/skills/stock-daily-brief/   skill 本體，routine clone 後會讀到
.github/workflows/                  每天抓資料的 GitHub Actions
data/                               Actions 每天 commit 的行情 JSON ← routine 讀這個
reports/                            HTML 報告（見下方「報告怎麼拿到」）
```

本機的 `~/.claude/skills/stock-daily-brief` 是指到這個 repo 的 symlink，
所以本機用和雲端跑的是同一份 skill，不會有兩份副本各自漂移。

## 為什麼是 public repo

要 clone **private** repo，必須先把 GitHub 接上 Claude 帳號並授權該 repo，
否則建立 routine 時會擋在 `403 You don't have access to a repository this routine uses`。
這裡選了改成 public 換取零設定，代價是追蹤清單與報告內容公開可搜尋。

要收回：把 repo 改回 private，到 <https://claude.ai/code> 接上 GitHub 並授權
stock-brief，兩個 routine 不用改就會恢復。

## 報告怎麼拿到

公開 repo 是匿名 clone，雲端**沒有 repo 寫入權限**，`git push` 會失敗。所以交付順序是：

1. **`SendUserFile`** 把 HTML 直接送到 routine 執行頁面（主要方式）
2. **最後一則訊息**寫完整戰報——收盤價、三大法人、融資融券、技術指標、消息重點、
   資料日期都在裡面，就算 HTML 完全送不出去也看得懂

`git push` 還是會試一次，成功就多一份存檔，失敗不重試也不中斷。

## 資料源備援

Yahoo Finance 對**本機 IP 和 GitHub Actions runner 都回 429**（query1／query2 全擋，
cookie + crumb 流程也拿不到）。Yahoo 一掛，技術指標全空、美股整個場次失效，
所以 `common.py` 的 `yahoo_chart()` 改成「先試 Yahoo，掛掉走備援」：

| 標的 | 備援來源 | 狀態 |
|---|---|---|
| 上市（.TW） | 證交所 `STOCK_DAY` 月成交檔 × 13 個月 | ✅ 實測可用 |
| 上櫃（.TWO） | 櫃買 `tradingStock` 月成交檔 × 13 個月 | ✅ 實測可用 |
| 加權指數 `^TWII` | 證交所 `MI_5MINS_HIST` | ✅ 實測可用 |
| 櫃買指數 `^TWOII` | 無 | ⚠️ Yahoo 掛掉時該列消失 |
| 美股個股／ADR | stockanalysis.com | ✅ 實測可用 |
| 美股指數 | SOXX／QQQ／SPY ETF 代理 | ⚠️ 非指數點位，見下 |

實際用了哪條路會寫進 `resolved.source` 並進 `warnings`，報告據實標註。
**目前每天實際上跑的都是備援路徑**，Yahoo 從沒成功過。

**美股指數是 ETF 代理，不是指數本身。** SOXX 五百多點 vs 費半六千多點，量級完全不同。
腳本會把名稱改成「費城半導體（SOXX ETF 代理，非指數點位）」，只有漲跌百分比可引用。
routine 的 prompt 也寫死了這條規則。

試過但不能用：Stooq（JS 驗證牆）、Nasdaq API（`Error while calling vendor`）、
TPEx `indexInfo/dailyClose` 與 `afterTrading/otcIndex`（回空）。

備援要打 13 個月的月檔，比 Yahoo 慢很多（台股兩檔約 2 分鐘）。刻意的取捨：
慢但拿得到，好過快但整份空白。

## 本機測試

```bash
python3 .claude/skills/stock-daily-brief/scripts/fetch_tw.py --out /tmp/data_tw.json
python3 .claude/skills/stock-daily-brief/scripts/fetch_us.py --out /tmp/data_us.json
```

看得到「寫出 ...｜交易日 YYYY-MM-DD」就是通了。只用標準函式庫，不需要 pip install。

手動觸發雲端那一段：

```bash
gh workflow run fetch-tw.yml        # 重抓台股資料
gh run list --workflow=fetch-tw.yml # 看結果
```

## 如果哪天想簡化

Anthropic 雲端環境若開放網路白名單（claude.ai/code → 環境設定 → Network access 改 Custom，
加入 `www.twse.com.tw`、`openapi.twse.com.tw`、`www.tpex.org.tw`、`query1.finance.yahoo.com`、
`query2.finance.yahoo.com`、`stockanalysis.com`），就能拿掉 GitHub Actions 這一段，
讓 routine 自己抓。屆時只要把兩個 routine 的 prompt 改回直接跑 `fetch_*.py` 即可。

## 注意

報告是公開資訊整理與技術指標計算，不是投資建議，也不預測價格。
