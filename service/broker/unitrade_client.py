"""
UniTrade API 封裝。

架構決策：login-per-request —— 每次下單都是 login() → order() → logout()，
不維持長連線（見 repo README 架構決策 #1）。

交易標的：外期（海外期貨，目前鎖定 CME 那斯達克微型期貨 MNQ，對應 TradingView
NQ1! 策略），走 ftrade（外期）API，不是 dtrade（內期/台灣期貨）。

參考文件：
- 登入 / 帳號查詢: https://pfcec.github.io/unitrade/API/unitrade/
- 外期下單教學: https://pfcec.github.io/unitrade/教學/外期下單/
- 外期下單物件 (ftrade.order): https://pfcec.github.io/unitrade/API/ftrade/

已於 2026-07-06 用 `pip install unitrade`（真的 PyPI 套件，含 Linux wheel）實際安裝驗證過：
`from unitrade.unitrade import *` 會匯出 Unitrade / DOrderObject / FOrderObject 等名稱。

2026-07-09 對照官方文件修正三個 bug（真實測試帳號下單時才發現，官方文件本身在
多處前後矛盾，別只看單一頁）：
1. login() 原本讀取不存在的 resp.error，實際上 LoginResponse 物件是
   ok / errorcode / errormsg。
2. 下單物件的 actno 原本直接沿用登入帳號，但登入帳號不一定等於可下單的
   「交易帳號」，回傳 MSG005「該帳號不允許操作」。已改成登入後呼叫
   get_accounts() 查詢正確的交易帳號並快取。
3. get_accounts() 是 Unitrade 實例方法 (self._api.get_accounts())，不是
   「開始」頁範例寫的 unitrade.get_accounts()（module-level，實際會噴
   AttributeError）。

2026-07-10 發現更根本的問題：原本用 dtrade（內期）下單，商品代碼隨便填了一個
過期的內期合約代碼 (MXFG5)，手機券商 App 顯示「商品代號錯誤」。但使用者要交易
的其實是那斯達克期貨（外期），跟內期是完全不同的 API 模組、不同的商品代碼格式
（拆成 exchange + symbol + maturitymonthyear，不是合併字串）。已整個改寫成呼叫
ftrade.order()，並且合約月份改成即時查詢目前有效合約（見 _resolve_front_month），
不再寫死月份代碼，避免同一個問題以後又發生一次。

2026-07-10 加上 safe_test_mode：使用者已經換成正式交易帳號測試（不是測試帳號，
真的可能成交），要求下單先改成限價單、掛在「絕對不可能成交」的價位，確認整條
路徑正常後才切回市價單。買單掛在參考價下方 SAFE_LIMIT_OFFSET_PCT（預設 20%），
賣單掛在上方，正常市況下不會有滑價大到吃到這個價位的可能。safe_test_mode
預設開啟，之後真的要送市價單時把它關掉（見 main.py 怎麼從環境變數帶進來）。

2026-07-10 safe_test_mode 的參考價來源改掉：原本用 fquote.query_tick_data_trade()
查目前成交價，結果這個帳號的外期報價權限沒開，回傳「不允許操作!」（下單權限
ftrade 跟報價權限 fquote 是分開授權的）。改成優先用 payload 裡帶的 price 欄位
（TradingView alert 觸發當下的 K 棒收盤價，Pine 端已經知道，不需要另外查）；
如果 payload 沒帶 price，才退回呼叫 fquote 查價當備援。
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import unitrade
from unitrade.unitrade import *  # noqa: F401,F403  (Unitrade, DOrderObject, FOrderObject 等)

from .product_map import resolve_foreign_product

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    ok: bool
    stage: str = ""          # "login" | "order"
    seq: str = ""
    errorcode: str = ""
    errormsg: str = ""


class UnitradeClient:
    """
    login-per-request 封裝。每次要下單/查歷史資料，都呼叫 login()，
    用完呼叫 logout()。不要在多個 request 之間共用同一個 instance。
    """

    def __init__(self, url: str, account: str, password: str, cert_path: str, cert_password: str,
                 safe_test_mode: bool = True, safe_limit_offset_pct: float = 0.2):
        self.url = url
        self.account = account          # 登入帳號 (userid)，不一定等於下單用的交易帳號
        self.password = password
        self.cert_path = cert_path
        self.cert_password = cert_password
        self._api: Optional["Unitrade"] = None
        self.trade_account: Optional[str] = None  # 登入後查到的實際可下單交易帳號 (actno)

        # safe_test_mode=True 時，下單一律送限價單、掛在「不可能成交」的價位
        # （買單掛在目前成交價下方 safe_limit_offset_pct，賣單掛在上方），用來
        # 在正式帳號上測試整條 pipeline 又不想真的成交。細節見檔案開頭註解。
        self.safe_test_mode = safe_test_mode
        self.safe_limit_offset_pct = safe_limit_offset_pct

    def login(self) -> OrderResult:
        self._api = Unitrade()
        self._api.on_error = lambda err: logger.error("UniTrade error: %s", err)

        resp = self._api.login(self.url, self.account, self.password, self.cert_path, self.cert_password)
        # LoginResponse 物件結構（見 https://pfcec.github.io/unitrade/開始/ 第4節）：
        # ok / errorcode / errormsg —— 之前這裡誤用了不存在的 resp.error，
        # 導致登入失敗時看不到真正的錯誤代碼/訊息。
        if not resp.ok:
            logger.error("UniTrade login failed: errorcode=%s errormsg=%s", resp.errorcode, resp.errormsg)
            return OrderResult(ok=False, stage="login", errorcode=resp.errorcode, errormsg=resp.errormsg)
        logger.info("UniTrade login ok")

        # 登入帳號不一定是可下單的交易帳號，需另外查詢（見官方 FAQ「該帳號不允許操作」章節）。
        # 注意 get_accounts() 是 Unitrade 實例方法（self._api.get_accounts()），
        # 不是 unitrade 模組層級的函式 —— 官方「開始」頁範例這裡寫錯了。
        try:
            accounts = self._api.get_accounts()
        except Exception as exc:  # noqa: BLE001  SDK 例外情況先攔下來轉成一般錯誤回傳
            logger.error("UniTrade get_accounts failed: %s", exc)
            return OrderResult(ok=False, stage="login", errormsg=f"get_accounts failed: {exc}")

        if not accounts:
            logger.error("UniTrade get_accounts returned empty list")
            return OrderResult(ok=False, stage="login", errormsg="no trading accounts available")

        self.trade_account = accounts[0]
        logger.info("UniTrade trading accounts: %s (using %s)", accounts, self.trade_account)
        return OrderResult(ok=True, stage="login")

    # 距離最後交易日幾天內就換到下一口合約，而不是死守「還沒過期」的那口。
    # 理由（使用者 2026-07-10 提出）：合約快到期時量會慢慢萎縮，實務上大概
    # 倒數一週左右市場就已經把量能轉去下一口熱門合約了，這時如果還死守
    # 最近到期的那口，容易碰到成交稀薄、滑價變大的問題。7 天是先抓一個
    # 保守值，之後如果覺得不準可以再調。
    ROLLOVER_BUFFER_DAYS = 7

    def _resolve_front_month(self, exchange: str, symbol: str) -> Optional[str]:
        """
        查詢目前應該交易的外期合約月份，回傳 maturitymonthyear (YYYYMM)。
        找不到就回傳 None。

        規則：先過濾掉已經過最後交易日的合約，剩下依到期日排序，跳過「距離
        最後交易日不到 ROLLOVER_BUFFER_DAYS 天」的合約（视为量能已經轉移到
        下一口），選第一個滿足緩衝天數的合約。如果全部合約都在緩衝期內
        （理論上不太會發生），退回選最後到期的那口，至少還能下單。

        這是為了避免像先前 dtrade 版本那樣把合約代碼寫死在設定裡，結果過期
        了都沒發現（2026-07-10 手機 App 回報「商品代號錯誤」才發現用的是
        2025 年的過期合約）。
        """
        resp = self._api.get_foreign_contracts(exchange, symbol, "F")
        if not resp.ok or not resp.data:
            logger.error("get_foreign_contracts(%s, %s) failed: %s", exchange, symbol, resp.error)
            return None

        today_dt = datetime.now()
        today = today_dt.strftime("%Y%m%d")
        valid = [c for c in resp.data if c.lasttradedate >= today]
        if not valid:
            logger.error("get_foreign_contracts(%s, %s) has no unexpired contract", exchange, symbol)
            return None

        valid.sort(key=lambda c: c.lasttradedate)

        for c in valid:
            last_trade_dt = datetime.strptime(c.lasttradedate, "%Y%m%d")
            days_left = (last_trade_dt - today_dt).days
            if days_left > self.ROLLOVER_BUFFER_DAYS:
                logger.info("front-month contract for %s/%s: %s (last trade date %s, %d days left)",
                            exchange, symbol, c.monthyear, c.lasttradedate, days_left)
                return c.monthyear

        # 全部都在緩衝期內：退回選到期最晚的那口，至少還能下單
        fallback = valid[-1]
        logger.warning("all contracts for %s/%s are within rollover buffer, falling back to %s (last trade %s)",
                        exchange, symbol, fallback.monthyear, fallback.lasttradedate)
        return fallback.monthyear

    def _get_last_price_from_fquote(self, exchange: str, symbol: str, maturitymonthyear: str) -> Optional[float]:
        """
        查目前成交價（fquote API 備援路徑）。查不到就回傳 None。

        2026-07-10 確認：這個帳號沒有 fquote（外期報價）權限，實際呼叫會回傳
        「不允許操作!」——下單權限 (ftrade) 跟報價權限 (fquote) 在這家券商是
        分開授權的。正常情況下 place_order() 會優先用 webhook payload 帶的
        price 欄位，不會走到這個方法；保留它是給之後申請到 fquote 權限、或是
        換成有權限的帳號時可以用。
        """
        try:
            resp = self._api.fquote.query_tick_data_trade(exchange, symbol, maturitymonthyear, "", "F")
        except Exception as exc:  # noqa: BLE001
            logger.error("query_tick_data_trade(%s, %s, %s) raised: %s", exchange, symbol, maturitymonthyear, exc)
            return None

        if not resp.ok or resp.data is None:
            logger.error("query_tick_data_trade(%s, %s, %s) failed: %s", exchange, symbol, maturitymonthyear,
                         getattr(resp, "error", ""))
            return None

        return resp.data.lastprice

    def _resolve_reference_price(self, signal: dict, exchange: str, symbol: str,
                                  maturitymonthyear: str) -> Optional[float]:
        """
        safe_test_mode 用來算「絕對不可能成交」限價的參考價。

        優先順序：
        1. webhook payload 裡的 price 欄位 —— Pine 端在 alert 觸發當下的 K 棒
           close，不需要額外查價，也不受這個帳號沒有 fquote 權限的限制。
        2. 沒帶 price 時才退回呼叫 fquote 查即時成交價（多半會失敗，見
           _get_last_price_from_fquote 的註解）。

        查不到（兩條路徑都沒有）就回傳 None，呼叫端要 fail closed，不能硬送
        限價 0。
        """
        raw_price = signal.get("price")
        if raw_price not in (None, "", 0, "0"):
            try:
                price = float(raw_price)
                if price > 0:
                    logger.info("using price from webhook payload as safe_test_mode reference price: %s", price)
                    return price
            except (TypeError, ValueError):
                logger.warning("payload price %r is not a valid number, falling back to fquote", raw_price)

        logger.info("no usable price in payload, falling back to fquote lookup (likely to fail without fquote permission)")
        return self._get_last_price_from_fquote(exchange, symbol, maturitymonthyear)

    def place_order(self, signal: dict) -> OrderResult:
        """
        signal 預期欄位:
          symbol   優先當成 TradingView ticker 查 product_map.py 的對照表
                   （例如 "NQ1!" -> CME/MNQ）；查不到就退回把這個值直接當
                   UniTrade 的 CME 商品代碼用（相容舊格式，例如直接填 "MNQ"）
          exchange 只有在 symbol 沒查到對照表時才會用到，預設 "CME"
          action   "buy" / "sell"
          qty      口數
          price    K 棒收盤價 (Pine 的 close)，safe_test_mode 開啟時用來算
                   限價要掛在哪（見 _resolve_reference_price）。這個帳號沒有
                   fquote 報價權限，所以 safe_test_mode 下沒有這個欄位會直接
                   失敗，不是選填。

        目前只處理開倉方向 buy/sell，"close" 邏輯留到之後再補
        （通常要另外查目前部位方向才能正確組出平倉單）。
        """
        if self._api is None or self.trade_account is None:
            return OrderResult(ok=False, stage="order", errormsg="not logged in")

        mapped = resolve_foreign_product(signal["symbol"])
        if mapped:
            exchange, symbol = mapped
            logger.info("resolved TradingView symbol %s -> UniTrade %s/%s", signal["symbol"], exchange, symbol)
        else:
            exchange = signal.get("exchange", "CME")
            symbol = signal["symbol"]

        maturitymonthyear = self._resolve_front_month(exchange, symbol)
        if not maturitymonthyear:
            return OrderResult(ok=False, stage="order",
                                errormsg=f"no valid unexpired contract found for {exchange}/{symbol}")

        bs = "B" if signal["action"] == "buy" else "S"

        ordertype = "M"
        price = 0
        if self.safe_test_mode:
            ref_price = self._resolve_reference_price(signal, exchange, symbol, maturitymonthyear)
            if ref_price is None:
                return OrderResult(ok=False, stage="order",
                                    errormsg="safe_test_mode: no price in payload and fquote lookup failed "
                                              "(this account has no fquote permission — Pine script must send "
                                              "a \"price\" field in the webhook payload)")
            # 買單掛在參考價下方、賣單掛在上方，正常市況下不會被吃到。
            offset = ref_price * self.safe_limit_offset_pct
            price = round(ref_price - offset if bs == "B" else ref_price + offset, 2)
            ordertype = "L"
            logger.info("safe_test_mode: ref_price=%s -> limit price=%s (bs=%s, offset_pct=%s)",
                        ref_price, price, bs, self.safe_limit_offset_pct)

        order_obj = FOrderObject()
        order_obj.actno = self.trade_account
        order_obj.subactno = ""
        order_obj.note = str(signal.get("signal_id", ""))[:20]
        order_obj.exchange = exchange
        order_obj.symbol = symbol
        order_obj.maturitymonthyear = maturitymonthyear
        order_obj.putorcall = "F"     # 期貨（不是選擇權）
        order_obj.bs = bs
        order_obj.ordertype = ordertype  # safe_test_mode 時強制 "L"（限價），平常是 "M"（市價）
        order_obj.price = price
        order_obj.stopprice = 0
        order_obj.orderqty = signal.get("qty", 1)
        order_obj.ordercondition = "R"  # ROD
        order_obj.opencloseflag = ""    # 空白 = 自動判斷新倉/平倉
        order_obj.dtrade = "N"          # 非當沖

        resp = self._api.ftrade.order(order_obj)
        return OrderResult(
            ok=resp.issend,
            stage="order",
            seq=resp.seq,
            errorcode=resp.errorcode,
            errormsg=resp.errormsg,
        )

    def get_history_bardata(self, productid: str, productkind: str = "1",
                             interval: str = "1K", days: int = 30, count: int = 500):
        """
        回測用歷史K線 —— 直接吃 UniTrade 自己的報價來源（跟實盤下單同一個資料源，
        不用另外接 TradingView 或第三方數據）。
        interval: "D" 日K / "1K" 分K。

        TODO: 這裡還是用內期的 dquote，現在下單已經改成外期 (ftrade)，回測資料
        應該要改用對應的外期報價元件 (fquote)，欄位/呼叫方式待查文件確認。
        backtest/ 引擎真的要動工時再一起處理。
        """
        if self._api is None:
            return None
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=days)
        return self._api.dquote.get_history_bardata(interval, start, end, productkind, productid, count)

    def logout(self) -> None:
        if self._api is not None:
            self._api.logout()
            self._api = None
