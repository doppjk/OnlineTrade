# 設定 UniTrade 測試帳號的 Secret Manager 密鑰

這些指令都在 GCP Cloud Shell 執行，帳號/密碼/憑證密碼全部由你自己填入、
自己執行，不要貼到跟 Claude 的對話裡（這些是你的交易帳號登入資訊）。

密鑰值裡如果有 `$`、`` ` ``、`"` 這類特殊字元，一律用**單引號**包起來，
避免被 bash 誤判成變數展開（之前 WEBHOOK_SECRET 踩過這個坑）。

## 1. 上傳 .pfx 憑證檔到 Cloud Shell

Cloud Shell 右上角「⋮」選單 → Upload → 選你的 `.pfx` 憑證檔，上傳後預設會在
家目錄（`~/`）。

## 2. 建立密鑰

```bash
PROJECT_ID=onlinetrader-501816

# 帳號
echo -n '你的UniTrade帳號' | gcloud secrets create UNITRADE_ACCOUNT \
  --data-file=- --project=$PROJECT_ID

# 交易密碼
echo -n '你的UniTrade密碼' | gcloud secrets create UNITRADE_PASSWORD \
  --data-file=- --project=$PROJECT_ID

# 憑證密碼
echo -n '你的憑證密碼' | gcloud secrets create UNITRADE_CERT_PASSWORD \
  --data-file=- --project=$PROJECT_ID

# 憑證本體（.pfx 二進位檔，換成你實際上傳的檔名）
gcloud secrets create UNITRADE_CERT \
  --data-file=~/你的憑證檔.pfx --project=$PROJECT_ID
```

## 3. 授權 Cloud Run 讀取這些密鑰

跟當初 WEBHOOK_SECRET 一樣，補一樣的 accessor 角色（服務帳號名稱跟之前一致）：

```bash
for SECRET in UNITRADE_ACCOUNT UNITRADE_PASSWORD UNITRADE_CERT_PASSWORD UNITRADE_CERT; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --project=$PROJECT_ID \
    --member="serviceAccount:146144319468-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

## 4. 部署（真的接測試帳號下單）

```bash
cd ~/OnlineTrade
DRY_RUN=false PROJECT_ID=$PROJECT_ID ./infra/deploy.sh
```

`infra/deploy.sh` 會把 `UNITRADE_CERT` 掛成容器裡的檔案
`/secrets/unitrade.pfx`，並設定 `UNITRADE_CERT_PATH` 指到那個路徑，
`UNITRADE_ACCOUNT`／`UNITRADE_PASSWORD`／`UNITRADE_CERT_PASSWORD` 則是一般密鑰
環境變數。`DRY_RUN=false` 才會真的呼叫 UniTrade login → 下單。

## 固定 IP（如果 UniTrade 測試環境要求登入 IP 白名單）

Cloud Run 預設對外連線用的是共用、會變動的 IP，如果 UniTrade 那邊要求登入 IP
白名單，用預設設定登入會被擋。需要另外設定固定對外 IP：

```bash
PROJECT_ID=onlinetrader-501816
REGION=asia-east1

# 1. 保留一個固定的對外 IP
gcloud compute addresses create unitrade-nat-ip \
  --region=$REGION --project=$PROJECT_ID

# 2. 建立 Cloud Router
gcloud compute routers create onlinetrader-router \
  --network=default --region=$REGION --project=$PROJECT_ID

# 3. 建立 Cloud NAT，綁定剛剛保留的固定 IP
gcloud compute routers nats create onlinetrader-nat \
  --router=onlinetrader-router \
  --region=$REGION \
  --nat-external-ip-pool=unitrade-nat-ip \
  --nat-all-subnet-ip-ranges \
  --project=$PROJECT_ID

# 4. 查出這個固定 IP 是多少，拿去給 UniTrade 那邊登記白名單
gcloud compute addresses describe unitrade-nat-ip \
  --region=$REGION --project=$PROJECT_ID --format="value(address)"
```

`infra/deploy.sh` 預設會把 Cloud Run 對外流量導去走這個固定 IP
（`USE_STATIC_IP=true` 是預設值）。如果還沒建立 Cloud NAT 就跑 deploy.sh，
可以先設 `USE_STATIC_IP=false` 跳過這段，等 Cloud NAT 建好、IP 也登記進
UniTrade 白名單後，再拿掉這個變數（或設回 true）重新部署。

## 已知缺口

`service/broker/unitrade_client.py` 的 `place_order()` 對 `"close"` action
目前只是簡單映射成賣出 (`bs="S"`)，還沒處理 UniTrade 下單物件的
`opencloseflag`（開倉/平倉旗標）。先只測 `buy`/`sell`（開倉），
真的要測平倉單前要先確認這個欄位怎麼填，不然可能變成開一個新的反向倉位
而不是平掉原本的倉位。
