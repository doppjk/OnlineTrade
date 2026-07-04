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

架構骨架，尚未實作策略邏輯。下一步：討論一個簡單策略，把整條路徑串起來（先在測試帳號上跑通 webhook → 風控 → 送出委託）。
