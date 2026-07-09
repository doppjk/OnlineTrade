"""
TradingView 商品代碼 → UniTrade 商品代碼對照表。

目的：Pine 腳本可以直接送 TradingView 自己的 ticker（例如 syminfo.ticker
拿到的 "NQ1!"），不用在每個策略的輸入欄位裡手動填一個容易忘記更新、也可能
過期的 UniTrade 商品代碼字串（就是 2026-07-10 那次「商品代號錯誤」的根因）。
main.py 收到 webhook 後，會先用這個表把 TradingView 代碼轉成 UniTrade
的 (exchange, symbol)，查不到才退回把 payload 的 symbol 直接當成 UniTrade
代碼用（相容舊的呼叫方式）。

目前只維護外期 (CME 為主)，使用者表示可能會交易微型台指（小台/微台），但
內期 (dtrade) 下單邏輯已經在 2026-07-10 拿掉，只剩 ftrade（外期）。之後真的
要交易內期商品時，要把 unitrade_client.py 的 dtrade 下單邏輯加回來，這裡的
內期對照也才有意義（目前先保留註解、不啟用）。

外期合約月份不用填在這裡 —— unitrade_client.py 的 _resolve_front_month()
會即時查詢目前有效（且已經過換月緩衝期）的合約，這個表只需要商品本身的
對照，不含月份。
"""

# TradingView ticker -> (UniTrade exchange, UniTrade symbol)
FOREIGN_PRODUCT_MAP: dict[str, tuple[str, str]] = {
    # 那斯達克 100
    "NQ1!":  ("CME", "MNQ"),   # 標準合約，對照到微型 (使用者目前選擇先用微型控制風險)
    "MNQ1!": ("CME", "MNQ"),   # TradingView 上如果直接看微型合約也會對到同一個
    # 以下先預留、還沒實際驗證過 UniTrade 商品代碼是否正確，用之前務必先查
    # get_foreign_products() / get_foreign_contracts() 確認代碼存在
    "ES1!":  ("CME", "MES"),   # S&P 500 -> 微型標普
    "YM1!":  ("CBOT", "MYM"),  # 道瓊 -> 微型道瓊（交易所代碼也還沒驗證）
    "RTY1!": ("CME", "M2K"),   # 羅素 2000 -> 微型羅素
}

# 內期 (台灣期交所) 對照 —— 先寫著備查，dtrade 下單邏輯還沒接回來，不能直接用。
# TradingView ticker -> UniTrade 內期商品代碼 (不含月份)
DOMESTIC_PRODUCT_MAP_TODO: dict[str, str] = {
    "TX1!":  "TXF",  # 台指期 -> 台指期貨（大台）
    "MTX1!": "MXF",  # 小台指期 -> 小型台指期貨（小台/微台，使用者提到可能會玩這個）
}


def resolve_foreign_product(tv_symbol: str) -> tuple[str, str] | None:
    """
    查 TradingView ticker 對應的 UniTrade (exchange, symbol)。
    查不到回傳 None，呼叫端應該要有 fallback（見 unitrade_client.py 使用方式）。
    """
    return FOREIGN_PRODUCT_MAP.get(tv_symbol)
