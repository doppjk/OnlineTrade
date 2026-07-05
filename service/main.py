"""
Cloud Run webhook 進入點 —— 最小可跑版本。

架構決策（見 repo README）：標準 Cloud Run，非常駐單例。每次 webhook 進來
才做「登入 UniTrade → 下單 → 登出」，在同一個 request 生命週期內完成。
部署時搭配 max-instances=1、concurrency=1，避免兩個 request 同時搶著
登入同一組帳號。

DRY_RUN 模式（預設開啟）：不會真的呼叫 UniTrade，只驗證密鑰/風控/流程並記錄，
方便在還沒接測試帳號密鑰前先確認 webhook 有正確收到訊號。
確認要接測試帳號時，把 DRY_RUN 設為 "false" 並補上 UNITRADE_* 環境變數。

還沒實作策略邏輯本身 —— 這裡只負責「收到訊號後怎麼處理」，策略還是在 TradingView 端。
"""
import os
import logging

from flask import Flask, request, jsonify

from risk import check_order
from broker.unitrade_client import UnitradeClient

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

# 簡單防重放去重。注意：這是 in-memory，Cloud Run instance 重啟或多開就會失效，
# 量大/正式上線後應改用 Firestore 之類的外部儲存。訊號量低的階段先這樣打通。
_seen_signal_ids = set()


@app.get("/healthz")
def healthz():
    return jsonify(status="ok", dry_run=DRY_RUN), 200


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify(error="invalid json"), 400

    # 1. 驗證共享密鑰（TradingView webhook 無法帶自訂 header，只能放在 payload 裡）
    if not WEBHOOK_SECRET or payload.get("secret") != WEBHOOK_SECRET:
        logger.warning("webhook rejected: bad secret")
        return jsonify(error="unauthorized"), 401

    safe_payload = {k: v for k, v in payload.items() if k != "secret"}
    logger.info("webhook received: %s", safe_payload)

    # 2. 防重放/去重
    signal_id = payload.get("signal_id")
    if not signal_id:
        return jsonify(error="missing signal_id"), 400
    if signal_id in _seen_signal_ids:
        logger.warning("duplicate signal_id ignored: %s", signal_id)
        return jsonify(status="duplicate ignored"), 200
    _seen_signal_ids.add(signal_id)

    # 3. 風控檢查（目前 risk/ 還是骨架，一律放行——見 risk/__init__.py 的警告註解）
    risk_result = check_order(payload)
    if not risk_result.ok:
        logger.warning("order blocked by risk check: %s", risk_result.reason)
        return jsonify(status="blocked", reason=risk_result.reason), 200

    # 4. DRY_RUN：只跑到這裡為止，不真的下單
    if DRY_RUN:
        logger.info("DRY_RUN=true，略過真實下單: %s", safe_payload)
        return jsonify(status="dry_run_ok", would_send=safe_payload), 200

    # 5. 真的呼叫 UniTrade：login → 下單 → logout
    client = UnitradeClient(
        url=os.environ["UNITRADE_URL"],
        account=os.environ["UNITRADE_ACCOUNT"],
        password=os.environ["UNITRADE_PASSWORD"],
        cert_path=os.environ["UNITRADE_CERT_PATH"],
        cert_password=os.environ["UNITRADE_CERT_PASSWORD"],
    )
    login_result = client.login()
    if not login_result.ok:
        logger.error("UniTrade login failed: %s", login_result.errormsg)
        return jsonify(status="error", stage="login", error=login_result.errormsg), 502

    try:
        order_result = client.place_order(payload)
        logger.info("order result: %s", order_result)
        return jsonify(
            status="ok" if order_result.ok else "error",
            stage=order_result.stage,
            seq=order_result.seq,
            errorcode=order_result.errorcode,
            errormsg=order_result.errormsg,
        ), (200 if order_result.ok else 502)
    finally:
        client.logout()


if __name__ == "__main__":
    # 本機測試用；Cloud Run 上由 Dockerfile 的 gunicorn 啟動
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
