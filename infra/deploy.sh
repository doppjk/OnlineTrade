#!/usr/bin/env bash
# 部署 service/ 到 Cloud Run。
# 反映架構決策：標準模式（無 --no-cpu-throttling）、max-instances=1、concurrency=1。
# 執行前請先確認：
#   - PROJECT_ID / REGION 已設定
#   - Secret Manager 已建立 WEBHOOK_SECRET、UNITRADE_* 等密鑰
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?請設定 PROJECT_ID}"
REGION="${REGION:-asia-east1}"
SERVICE_NAME="${SERVICE_NAME:-onlinetrader-webhook}"

gcloud run deploy "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source ./service \
  --max-instances 1 \
  --concurrency 1 \
  --allow-unauthenticated \
  --set-secrets "WEBHOOK_SECRET=WEBHOOK_SECRET:latest" \
  # TODO: 補上 UniTrade 帳號/密碼/憑證相關的 --set-secrets 或 --set-env-vars
