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

尚未放入實際策略檔——等簡單策略定案後補上。
