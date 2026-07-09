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

2026-07-09 發現：如果使用者圖表開的不是連續合約（"NQ1!"），而是特定到期月份
的合約（例如直接選 CME 9月的微型那斯達克），syminfo.ticker 回傳的是
"MNQU26" 這種「已經含月份代碼」的字串，不會命中 FOREIGN_PRODUCT_MAP（表裡
只有 "NQ1!"/"MNQ1!" 這種連續合約代碼），於是整串被當成 UniTrade symbol 直接
拿去查 get_foreign_contracts("CME", "MNQU26", ...)，但這個 API 要的是不含
月份的基礎代碼 "MNQ"，查不到，回傳 errormsg 空字串、下單失敗
("no valid unexpired contract found for CME/MNQU26")。
加了 _parse_dated_contract() 來拆解這種格式：從已知的基礎商品代碼
（EXCHANGE_BY_BASE_SYMBOL 的 key）比對前綴，剩下的部分如果符合「一個月份
代碼字母 + 2或4位數年份」就當作到期月份合約，取出基礎代碼。這樣不管使用者
圖表開的是連續合約還是特定到期月合約，都能正確解析。
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

# 基礎商品代碼 -> 交易所。用於解析「使用者圖表開在特定到期月合約」時
# syminfo.ticker 回傳的已含月份代碼字串（例如 "MNQU26"），見上面 2026-07-09
# 的說明。key 要跟 FOREIGN_PRODUCT_MAP 裡各筆的 UniTrade symbol 一致。
EXCHANGE_BY_BASE_SYMBOL: dict[str, str] = {
    "MNQ": "CME",
    "NQ":  "CME",
    "MES": "CME",
    "ES":  "CME",
    "MYM": "CBOT",
    "YM":  "CBOT",
    "M2K": "CME",
    "RTY": "CME",
}

# CME 期貨月份代碼（單一英文字母），用來判斷字串尾端是不是「月份代碼 + 年份」。
_MONTH_CODES = set("FGHJKMNQUVXZ")


def _parse_dated_contract(tv_symbol: str) -> str | None:
    """
    嘗試把「已經含到期月份代碼」的 ticker（例如 "MNQU26"）拆成基礎商品代碼
    （"MNQ"）。不是這種格式就回傳 None。

    比對邏輯：依基礎代碼長度由長到短嘗試（避免 "NQ" 誤吃到 "MNQ" 開頭的
    "MNQU26" 前兩碼 "MN"），確認剩餘部分是「1 個月份代碼字母 + 2 或 4 位數
    年份」才算符合，不然像 "NQ1!" 這種連續合約代碼也可能誤判（"1!" 不符合
    月份代碼+數字年份的格式，所以不會誤判，但還是用長度優先降低風險）。
    """
    for base in sorted(EXCHANGE_BY_BASE_SYMBOL, key=len, reverse=True):
        if not tv_symbol.startswith(base):
            continue
        rest = tv_symbol[len(base):]
        if len(rest) in (3, 5) and rest[0] in _MONTH_CODES and rest[1:].isdigit():
            return base
    return None


def resolve_foreign_product(tv_symbol: str) -> tuple[str, str] | None:
    """
    查 TradingView ticker 對應的 UniTrade (exchange, symbol)。
    先比對連續合約對照表 (FOREIGN_PRODUCT_MAP)，查不到再嘗試當作「已含到期
    月份代碼」的格式解析 (_parse_dated_contract)，兩者都查不到才回傳 None，
    呼叫端要有 fallback（見 unitrade_client.py 使用方式）。
    """
    mapped = FOREIGN_PRODUCT_MAP.get(tv_symbol)
    if mapped:
        return mapped

    base = _parse_dated_contract(tv_symbol)
    if base:
        return EXCHANGE_BY_BASE_SYMBOL[base], base

    return None
