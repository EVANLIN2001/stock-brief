# stock-brief

台股／美股盤後戰報。跑在 Claude Code Routine（Anthropic 雲端），電腦關機也照跑。

追蹤標的：台積電 2330、台半 5425、美光 MU。
要增刪標的改 `.claude/skills/stock-daily-brief/assets/watchlist.json`，不用動程式。
**改完要 push，下一次執行才會吃到新版本。**

## 排程

| 場次 | 台北時間 | Cron (UTC) | Routine ID |
|---|---|---|---|
| 台股 | 週一～五 16:00 | `0 8 * * 1-5` | `trig_01GgVN5ayfpKq6biKQ7aWW9S` |
| 美股 | 週二～六 06:00 | `0 22 * * 1-5` | `trig_01NREP3f1faZGGqeTUmiT3FA` |

美股排週二到週六，因為對應的是週一到週五的美股交易日。美股夏令 04:00、冬令 05:00
（台北時間）收盤，06:00 兩種情況都拿得到完整收盤。

管理介面：<https://claude.ai/code/routines>

## 結構

```
.claude/skills/stock-daily-brief/   Routine 在雲端會讀到的 skill
reports/                            HTML 報告（見下方「報告存不回來」）
```

本機的 `~/.claude/skills/stock-daily-brief` 是指到這個 repo 的 symlink，
所以本機用和雲端跑的是同一份 skill，不會有兩份副本各自漂移。

## 為什麼是 public repo

Routine 跑在雲端，只看得到 clone 進去的 repo。要 clone **private** repo 必須先把
GitHub 接上 Claude 帳號並授權該 repo，否則建立 routine 時會擋在：

```
403 You don't have access to a repository this routine uses.
```

這裡選了改成 public 換取零設定。代價是追蹤清單與報告內容公開可搜尋。
若日後要收回：把 repo 改回 private，到 <https://claude.ai/code> 接上 GitHub
並授權 stock-brief，兩個 routine 不用改就會恢復。

## 報告存不回來

公開 repo 是匿名 clone，**雲端沒有寫入權限，`git push` 會失敗**。
所以每天的成品是 **routine 執行結果頁面上的最後一則訊息**，不是 `reports/` 裡的 HTML。
兩個 routine 的 prompt 都已經寫明：push 失敗不重試、不中斷，並且最後訊息要能獨立看懂
（含收盤價、三大法人、融資融券、技術指標、消息重點、資料日期）。

要讓 HTML 真的存進 repo，就得給雲端寫入權限 —— 也就是回頭走上面 private + 授權那條路。

## 本機測試

```bash
python3 .claude/skills/stock-daily-brief/scripts/fetch_tw.py --out /tmp/data_tw.json
python3 .claude/skills/stock-daily-brief/scripts/fetch_us.py --out /tmp/data_us.json
```

看得到「寫出 ...｜交易日 YYYY-MM-DD」就是通了。stdout 的 warnings 要看一下。
只用標準函式庫，不需要 pip install。

## 資料源備援（Yahoo 429 對策）

2026-08-06 實測：Yahoo `query1` 與 `query2` 兩個 host 對本機 IP 全回 429，
連 cookie + crumb 流程也拿不到。Yahoo 一掛，技術指標全空、美股整個場次失效。

所以 `common.py` 的 `yahoo_chart()` 已改成「先試 Yahoo，掛掉走備援」：

| 標的 | 備援來源 | 狀態 |
|---|---|---|
| 上市（.TW） | 證交所 `STOCK_DAY` 月成交檔 × 13 個月 | ✅ 實測可用 |
| 上櫃（.TWO） | 櫃買 `tradingStock` 月成交檔 × 13 個月 | ✅ 實測可用 |
| 加權指數 `^TWII` | 證交所 `MI_5MINS_HIST` | ✅ 實測可用 |
| 櫃買指數 `^TWOII` | 無 | ⚠️ Yahoo 掛掉時該列消失 |
| 美股個股／ADR | stockanalysis.com | ✅ 實測可用 |
| 美股指數 | SOXX／QQQ／SPY ETF 代理 | ⚠️ 非指數點位，見下 |

實際用了哪條路會寫進 `resolved.source` 並進 warnings，報告據實標註。

**美股指數是 ETF 代理，不是指數本身。** SOXX 五百多點 vs 費半六千多點，
量級完全不同。腳本會把名稱改成「費城半導體（SOXX ETF 代理，非指數點位）」，
只有漲跌百分比可引用。

試過但不能用的來源：Stooq（JS 驗證牆）、Nasdaq API（`Error while calling vendor`）、
TPEx 的 `indexInfo/dailyClose` 與 `afterTrading/otcIndex`（回空）。

備援路徑要打 13 個月的月檔，比 Yahoo 慢很多（台股兩檔約 1–2 分鐘），這是刻意的取捨：
慢但拿得到，好過快但整份空白。

**雲端網路白名單**
Routine 環境若只放行套件庫等常見開發網域，財經資料來源會被擋，
徵兆是 403 加上 `x-deny-reason: host_not_allowed`。
要在環境設定把 Network access 改成 Custom 並加入：

```
openapi.twse.com.tw
www.twse.com.tw
www.tpex.org.tw
query1.finance.yahoo.com
query2.finance.yahoo.com
```

兩個 routine 的 prompt 都會在遇到這個狀況時明確回報被擋的網域，
而不是拿 WebSearch 湊數字充數。

## 注意

報告是公開資訊整理與技術指標計算，不是投資建議，也不預測價格。
