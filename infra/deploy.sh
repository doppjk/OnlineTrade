#!/usr/bin/env bash
# 部署 service/ 到 Cloud Run。
# 反映架構決策：標準模式（無 --no-cpu-throttling）、max-instances=1、concurrency=1。
# 執行前請先確認：
#   - PROJECT_ID / REGION 已設定
#   - Secret Manager 已建立以下密鑰（見 infra/setup_unitrade_secrets.md）：
#     WEBHOOK_SECRET, UNITRADE_ACCOUNT, UNITRADE_PASSWORD,
#     UNITRADE_CERT_PASSWORD, UNITRADE_CERT（.pfx 憑證本體）
#   - 2026-07-09 確認 UniTrade 測試環境不要求 IP 白名單，預設不啟用固定 IP。
#     如果之後改成需要白名單，見 infra/setup_unitrade_secrets.md 的「固定 IP」
#     章節建立 Cloud NAT，再設 USE_STATIC_IP=true。
#
# DRY_RUN 預設為 true（安全預設值，不會真的呼叫 UniTrade）。
# 要接測試帳號真的送出委託時，執行：DRY_RUN=false ./infra/deploy.sh
#
# SAFE_TEST_MODE 預設為 true：DRY_RUN=false 時會強制送限價單、掛在不可能成交
# 的價位（買單掛目前成交價下方 SAFE_LIMIT_OFFSET_PCT、賣單掛上方），這是為了
# 在正式帳號上測試 pipeline 又不想真的成交（2026-07-10 使用者換成正式帳號後
# 提出的需求）。確認沒問題、真的要送市價單成交時，執行：
#   DRY_RUN=false SAFE_TEST_MODE=false ./infra/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?請設定 PROJECT_ID}"
REGION="${REGION:-asia-east1}"
SERVICE_NAME="${SERVICE_NAME:-onlinetrader-webhook}"
DRY_RUN="${DRY_RUN:-true}"
UNITRADE_URL="${UNITRADE_URL:-https://viploginm.pfctrade.com}"
USE_STATIC_IP="${USE_STATIC_IP:-false}"
VPC_NETWORK="${VPC_NETWORK:-default}"
VPC_SUBNET="${VPC_SUBNET:-default}"
SAFE_TEST_MODE="${SAFE_TEST_MODE:-true}"
SAFE_LIMIT_OFFSET_PCT="${SAFE_LIMIT_OFFSET_PCT:-0.2}"

NETWORK_FLAGS=()
if [ "$USE_STATIC_IP" = "true" ]; then
  NETWORK_FLAGS=(--network="$VPC_NETWORK" --subnet="$VPC_SUBNET" --vpc-egress=all-traffic)
fi

gcloud run deploy "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source ./service \
  --max-instances 1 \
  --concurrency 1 \
  --allow-unauthenticated \
  "${NETWORK_FLAGS[@]}" \
  --set-env-vars "DRY_RUN=${DRY_RUN},UNITRADE_URL=${UNITRADE_URL},UNITRADE_CERT_PATH=/secrets/unitrade.pfx,SAFE_TEST_MODE=${SAFE_TEST_MODE},SAFE_LIMIT_OFFSET_PCT=${SAFE_LIMIT_OFFSET_PCT}" \
  --set-secrets "WEBHOOK_SECRET=WEBHOOK_SECRET:latest,UNITRADE_ACCOUNT=UNITRADE_ACCOUNT:latest,UNITRADE_PASSWORD=UNITRADE_PASSWORD:latest,UNITRADE_CERT_PASSWORD=UNITRADE_CERT_PASSWORD:latest,/secrets/unitrade.pfx=UNITRADE_CERT:latest"
