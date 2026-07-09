"""
UniTrade API 封裝。

架構決策：login-per-request —— 每次下單都是 login() → order() → logout()，
不維持長連線（見 repo README 架構決策 #1）。

參考文件：
- 登入 / 帳號查詢: https://pfcec.github.io/unitrade/API/unitrade/
- 下單 (dtrade.order):  https://pfcec.github.io/unitrade/API/dtrade/
- 歷史K線 (dquote.get_history_bardata): https://pfcec.github.io/unitrade/API/dquote/

已於 2026-07-06 用 `pip install unitrade`（真的 PyPI 套件，含 Linux wheel）實際安裝驗證過：
`from unitrade.unitrade import *` 會匯出 Unitrade / DOrderObject 等名稱，且 DOrderObject
欄位與這裡的用法一致。login()/order() 的呼叫方式尚未用真實帳密實際下過單，
第一次接測試帳號時仍要留意錯誤訊息。

2026-07-09 對照官方文件（開始頁 https://pfcec.github.io/unitrade/開始/）修正一個 bug：
login() 原本讀取 resp.error（不存在的欄位），實際上 LoginResponse 物件是
ok / errorcode / errormsg，已修正並把 errorcode 也一起往上傳。

2026-07-09 修正第二個 bug（真實測試帳號下單回傳 MSG005「該帳號不允許操作」才發現）：
下單物件的 actno 原本直接沿用登入帳號 (self.account)，但官方 FAQ
(https://pfcec.github.io/unitrade/常見問題/下單失敗/) 說明登入帳號不一定等於
可下單的「交易帳號」，要在登入成功後另外查詢交易帳號清單，下單時要用清單裡的
7 碼交易帳號當 actno。已修正為登入後查詢並快取。

2026-07-09 修正第三個 bug：get_accounts() 一開始誤用「開始」頁範例寫的
unitrade.get_accounts()（module-level function），實際部署後噴
`module 'unitrade' has no attribute 'get_accounts'`。對照 API Reference 頁，
get_accounts()／login()／dtrade 等其實都列在 `Unitrade` 類別底下，是實例方法，
「開始」頁的範例本身寫錯（前面用 api = Unitrade()，後面卻寫 unitrade.get_accounts()）。
已改成 self._api.get_accounts()，跟常見問題頁的範例 api.get_accounts() 一致。
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import unitrade
from unitrade.unitrade import *  # noqa: F401,F403  (Unitrade, DOrderObject 等)

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

    def __init__(self, url: str, account: str, password: str, cert_path: str, cert_password: str):
        self.url = url
        self.account = account          # 登入帳號 (userid)，不一定等於下單用的交易帳號
        self.password = password
        self.cert_path = cert_path
        self.cert_password = cert_password
        self._api: Optional["Unitrade"] = None
        self.trade_account: Optional[str] = None  # 登入後查到的實際可下單交易帳號 (actno)

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

    def place_order(self, signal: dict) -> OrderResult:
        """
        signal 預期欄位: symbol (UniTrade 商品代碼), action ("buy"/"sell"), qty (int)。
        目前只處理開倉方向 buy/sell，"close" 邏輯留到策略定案後再補
        （通常要另外查目前部位方向才能正確組出平倉單）。
        """
        if self._api is None or self.trade_account is None:
            return OrderResult(ok=False, stage="order", errormsg="not logged in")

        order_obj = DOrderObject(
            actno=self.trade_account,
            subactno="",
            productid=signal["symbol"],
            bs="B" if signal["action"] == "buy" else "S",
            ordertype="M",        # 市價單，先求打通；之後可依需求改限價 (L)
            price=0,
            orderqty=signal.get("qty", 1),
            ordercondition="R",   # ROD
            opencloseflag="",
            dtrade="N",
            note=str(signal.get("signal_id", ""))[:20],
        )
        resp = self._api.dtrade.order(order_obj)
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
