FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TODO: 補上 UniTrade SDK 的安裝步驟（見 requirements.txt 註解）
# TODO: 若 UniTrade 登入需要憑證檔 (.pfx)，透過 Secret Manager 掛載，
#       不要 COPY 進 image。

COPY . .

ENV PORT=8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 30 main:app
