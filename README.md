# stock-brief

台股／美股盤後戰報。給 Claude Code Routine 在雲端每天自動跑用的。

追蹤標的：台積電 2330、台半 5425、美光 MU。
要增刪標的改 `.claude/skills/stock-daily-brief/assets/watchlist.json`，不用動程式。

## 結構

```
.claude/skills/stock-daily-brief/   Routine 在雲端會讀到的 skill
reports/                            每日產出的 HTML 報告
```

Routine 跑在 Anthropic 雲端，只看得到這個 repo 裡的檔案，所以 skill 必須 commit 進來
才會生效。改完 skill 記得 push，下一次執行才會吃到新版本。

## 本機測試

設好 Routine 之前先在本機確認腳本會動，比較省時間：

```bash
python3 .claude/skills/stock-daily-brief/scripts/fetch_tw.py --out /tmp/data_tw.json
python3 .claude/skills/stock-daily-brief/scripts/fetch_us.py --out /tmp/data_us.json
```

看得到「寫出 ...｜交易日 YYYY-MM-DD」就是通了。stdout 的 warnings 要看一下，
常見的是證交所日成交檔比 Yahoo 慢一天，腳本會自動改用 Yahoo 並標註來源。

只用標準函式庫，不需要 pip install。

## 雲端環境需要的網路白名單

Routine 的 Default 環境只放行套件庫等常見開發網域，財經資料來源會被擋。
要在環境設定把 Network access 改成 Custom 並加入：

```
openapi.twse.com.tw
www.twse.com.tw
www.tpex.org.tw
query1.finance.yahoo.com
query2.finance.yahoo.com
```

被擋的徵兆是執行紀錄裡出現 403 與 `x-deny-reason: host_not_allowed`。

## 注意

報告是公開資訊整理與技術指標計算，不是投資建議，也不預測價格。
