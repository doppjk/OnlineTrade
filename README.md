# OnlineTrader

自動化交易 pipeline：TradingView (Pine Script v6) → webhook → Google Cloud Run (Python) → 統一期貨 UniTrade API 下單，並在 Cloud Run 端做風控與安全檢查。

最終目標：把這個 repo 演進成一個「餵策略進去、agent 自動驗證/回測」的工具。

## 架構總覽

```
TradingView (Pine v6 strategy/indicator)
        │  alert() → webhook (JSON payload, 含共享密鑰欄位)
        ▼
Cloud Run (service/)                          ← 標準模式，非常駐單例
  1. 驗證 payload 共享密鑰 + 防重放
  2. 風控檢查 (risk/)：部位上限、每日虧損停損、交易時段、重複訊號
  3. 呼叫 UniTrade：login → 下單 → logout（單次 request 內完成）
        │
        ▼
統一期貨 UniTrade API (憑證式登入, Python SDK)
```

## 架構決策（2026-07-05 確認）

1. **部署模式**：標準 Cloud Run（scale-to-zero），不做 always-on CPU 常駐單例。因為交易頻率是波段、非當沖，對延遲不敏感，訊號到達時才「登入 → 下單 → 登出」，做完即結束該次 request。額外設定 `max-instances=1`、`concurrency=1` 當保險，避免兩個 webhook 同時搶著登入同一組帳號。這個組合預期完全落在 Cloud Run 免費額度內。
2. **回測/驗證方式**：策略邏輯額外用 Python 鏡射一份（見 `backtest/`），不只依賴 TradingView 內建 Strategy Tester。這是未來「agent 自動驗證/回測任意策略」的基礎，代價是要維護 Pine（實盤訊號）與 Python（回測）兩份邏輯的一致性。
3. **測試環境**：已有統一期貨測試帳號（可送出委託，但不會真的成交），先用它跑通整條 pipeline，之後才切正式帳號。
4. **Secrets**：憑證檔 (.pfx)、憑證密碼、交易密碼、webhook 共享密鑰一律走 Google Secret Manager，不進 repo（見 `.gitignore`）。

## 資料夾結構

- `pine/` — Pine Script v6 指標/策略原始檔
- `service/` — Cloud Run webhook 接收 + 下單服務（Python）
  - `main.py` — webhook 進入點（驗證密鑰 → 風控 → 呼叫 broker）
  - `risk/` — 風控規則（部位上限、每日虧損停損、交易時段檢查）
  - `broker/` — UniTrade API 封裝（login/下單/logout）
- `backtest/` — 策略邏輯的 Python 鏡射版本 + 回測引擎
- `infra/` — 部署腳本 (gcloud run deploy 設定)

## 現況

`service/` 已經是可以跑的最小版本：webhook 驗證密鑰、防重放去重、風控（骨架，一律放行）、DRY_RUN 模式（預設開啟，不會真的呼叫 UniTrade）。`broker/unitrade_client.py` 已接上真的 `unitrade` SDK，欄位對照官方套件驗證過，但還沒用真實測試帳號實際下過單。

策略方面先擱置真正想交易的 `ma300_breakout_retest_strategy.pine`（條件嚴格、訊號稀疏，驗證起來費工），改用邏輯簡單、會頻繁觸發的 `ema_crossover_pipeline_test.pine`（EMA 9/21 交叉）跟純粹測速用的 `webhook_ping_test.pine` 打通 pipeline（細節見 `pine/README.md`）。

**Pipeline 已於 2026-07-08 完整跑通（DRY_RUN）**：Cloud Run 服務部署成功（`onlinetrader-webhook`，asia-east1），TradingView alert（webhook_ping_test.pine，1 分鐘線）→ Cloud Run `/webhook` → 密鑰驗證 → DRY_RUN 略過下單，全程 log 可見、每分鐘穩定觸發一次。

**真實測試帳號下單已於 2026-07-09 驗證成功**：`DRY_RUN=false` 接上 UniTrade 測試帳號，webhook → 風控 → UniTrade login → 下單，回傳 `{"status":"ok","seq":"0002",...}`，委託單真的送出去了。過程中對照官方文件修了三個 `broker/unitrade_client.py` 的 bug（登入回傳欄位名稱、下單帳號要另外查詢 `get_accounts()`、`get_accounts()` 是實例方法不是模組函式），細節見該檔案開頭註解。登入網址也已更新為 `viploginm.pfctrade.com`。UniTrade 測試環境確認不要求 IP 白名單，`infra/deploy.sh` 的固定 IP 功能預設關閉。

**2026-07-10 修正下單標的**：手機券商 App 回報委託失敗「商品代號錯誤」，發現下單邏輯原本誤用內期 (`dtrade`) API 跟寫死、已過期的內期合約代碼。實際要交易的是那斯達克期貨（外期），已改成呼叫 `ftrade.order()`，商品定為 CME 微型那斯達克期貨 MNQ，合約月份改成即時查詢目前未過期的最近合約（`_resolve_front_month()`），不再寫死月份，避免同樣的過期問題再發生。`ma300_breakout_retest_strategy.pine` 訊號稀疏的問題已確認不用處理（該策略先擱置）。

**已擱置，不用處理**：`ma300_breakout_retest_strategy.pine` 訊號稀疏的問題（使用者已確認不需要調整，這個策略先放著）。

**2026-07-10 新增 SAFE_TEST_MODE + 商品對照表**：使用者已換成正式交易帳號測試，要求避免真的成交。`unitrade_client.py` 新增 `safe_test_mode`（預設開啟）：下單時查目前成交價，強制送限價單、掛在買單價格下方/賣單價格上方 20%（`SAFE_LIMIT_OFFSET_PCT`，可調）的不可能成交價位，確認沒問題再手動關閉（`SAFE_TEST_MODE=false`）改回市價單。另外新增 `service/broker/product_map.py`，Pine 腳本改成直接送 `syminfo.ticker`，Cloud Run 端查表轉成 UniTrade 的 (exchange, symbol)，不用再手動填商品代碼（這是這幾天第二次因為手動填商品代碼出包）。合約換月邏輯也加了緩衝期（`ROLLOVER_BUFFER_DAYS`，預設 7 天），避免用到量能已經萎縮的即將到期合約。

下一步：用 MNQ + SAFE_TEST_MODE 重新跑一次完整的下單測試（含真實 TradingView alert 觸發，不是手動 curl），確認限價單有正確掛出去、狀態是「委託成功」但沒有成交；之後解決 `unitrade_client.py` 裡 `"close"` action 的 opencloseflag 缺口（目前只驗證過 `buy` 開倉單），並開始討論 Python 鏡射回測引擎（`backtest/`）怎麼做（含外期報價 `fquote` 怎麼接）。
