"""
Cloud Run webhook 進入點。

架構決策（見 repo README）：標準 Cloud Run，非常駐單例。
每次 webhook 進來才做「登入 UniTrade → 下單 → 登出」，在同一個 request
生命週期內完成，不維持長連線。部署時搭配 max-instances=1、concurrency=1，
避免兩個 request 同時搶著登入同一組帳號。

目前只有骨架，策略/風控/下單邏輯都還沒實作 —— 等簡單策略定案後補上。
"""
import os
import logging

from flask import Flask, request, jsonify

# from risk import check_order          # TODO: 實作後打開
# from broker.unitrade_client import UnitradeClient  # TODO: 實作後打開

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # 從 Secret Manager 掛進來


@app.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify(error="invalid json"), 400

    # 1. 驗證共享密鑰（TradingView webhook 無法帶自訂 header，只能放在 payload 裡）
    if not WEBHOOK_SECRET or payload.get("secret") != WEBHOOK_SECRET:
        logger.warning("webhook rejected: bad secret")
        return jsonify(error="unauthorized"), 401

    # TODO: 2. 防重放/去重 — 用 payload["signal_id"] 檢查是否已處理過
    # TODO: 3. 風控檢查 — check_order(payload)，任何一項失敗就整單擋下並記錄
    # TODO: 4. 呼叫 UnitradeClient：login() → place_order(payload) → logout()
    # TODO: 5. 記錄結果 / 失敗時發告警通知

    logger.info("webhook received: %s", {k: v for k, v in payload.items() if k != "secret"})
    return jsonify(status="received"), 200


if __name__ == "__main__":
    # 本機測試用；Cloud Run 上由 Dockerfile 的 gunicorn 啟動
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
