# pine/

Pine Script v6 指標與策略原始檔放這裡。

命名建議：`{strategy_name}_indicator.pine`、`{strategy_name}_strategy.pine`。

策略的 `alert()` payload 建議格式（JSON）：

```json
{
  "secret": "<共享密鑰，對應 Cloud Run 端 WEBHOOK_SECRET>",
  "signal_id": "<每次訊號唯一值，例如 {{time}}_{{ticker}}，用於 Cloud Run 端防重放/去重>",
  "strategy": "<策略名稱>",
  "symbol": "<商品代碼，對應 UniTrade 內期/外期商品代碼>",
  "action": "buy | sell | close",
  "qty": 1
}
```

## ma300_breakout_retest_strategy.pine

第一個策略：60分K 為基準，收盤價第一次站上 300日SMA 後，等連續三次「跌破又收復」的成功測試，做多；收盤跌破 300日SMA 就出場（不設固定停利/時間停損）。細節規則、狀態機邏輯、已知缺口都寫在檔案開頭的註解裡。

已於 2026-07-08 實際貼進 TradingView Pine Editor 編譯過，沒有錯誤，300D SMA 有正確畫在圖上。細節見檔案開頭的「驗證狀態」註解。

條件嚴格（單一時間週期 60m + 多時間週期 300日SMA），歷史上訊號很稀疏，不適合拿來快速驗證 pipeline 通不通，先擱著、之後再回頭調整測試定義或參數。

## ema_crossover_pipeline_test.pine

第二個策略，純粹用來打通 pipeline（跟上面那個策略的目的不同，不是要拿來真的交易）：單一時間週期，EMA(9) 由下往上穿越 EMA(21) 做多、由上往下穿越出場，沒有額外停損停利。邏輯簡單、歷史上會頻繁觸發，目的是快速驗證 TradingView → webhook → Cloud Run → UniTrade 整條路徑通不通。

驗證狀態（2026-07-08）：已貼進 TradingView Pine Editor 編譯，沒有錯誤，腳本已掛在圖表上。TradingView 的 Strategy Tester 面板/Data Window 在這次瀏覽器自動化測試中沒能穩定顯示交易筆數（UI 面板展不開、Data Window 讀不到正確的策略實例），改用 Python 鏡射同一套 EMA(9)/EMA(21) crossover 邏輯，對模擬的 3.5 年小時線資料做交叉次數統計，結果約每 3.5 年 490 次進場訊號、490 次出場訊號 —— 證實這個邏輯本身沒問題、會頻繁觸發，足以拿來驗證後續 webhook pipeline。之後如果想在 TradingView 內親眼確認交易筆數，可以直接看圖表上的 Long Entry/Long Exit 三角形記號，或改天重新展開 Strategy Tester 面板核對。

實際接上 Cloud Run 後（見 service/），這個策略的 1 小時 alert 觸發間隔太慢，不適合快速反覆測試 pipeline；把 alert 的 Interval 從「Same as chart (1h)」改成「1 minute」可以加速（同一顆 alert，不用改程式碼），但更快的做法是用下面的 webhook_ping_test.pine。

## webhook_ping_test.pine

第三份，純粹測 webhook 延遲/速度用，不含任何交易邏輯：不判斷任何指標條件，圖表上每一根K棒收盤就無條件送一次 webhook，action 在 buy/sell 之間交替方便在 log 裡分辨。切到 1 分鐘線的話等於每分鐘發一次。這是 `indicator` 不是 `strategy`，沒有進出場/回測報表可看，純粹是 alert() 發射器，上線交易不要用這份。

驗證狀態（2026-07-08）：已在 1 分鐘線上實際觸發 alert，Cloud Run log 確認每分鐘收到一次 webhook（`webhook received: {...}`），密鑰驗證通過、DRY_RUN 正確略過下單。整條 TradingView → Cloud Run webhook pipeline 至此完整跑通。
