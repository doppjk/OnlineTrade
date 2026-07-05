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
        self.account = account
        self.password = password
        self.cert_path = cert_path
        self.cert_password = cert_password
        self._api: Optional["Unitrade"] = None

    def login(self) -> OrderResult:
        self._api = Unitrade()
        self._api.on_error = lambda err: logger.error("UniTrade error: %s", err)

        resp = self._api.login(self.url, self.account, self.password, self.cert_path, self.cert_password)
        if not resp.ok:
            logger.error("UniTrade login failed: %s", resp.error)
            return OrderResult(ok=False, stage="login", errormsg=resp.error)
        return OrderResult(ok=True, stage="login")

    def place_order(self, signal: dict) -> OrderResult:
        """
        signal 預期欄位: symbol (UniTrade 商品代碼), action ("buy"/"sell"), qty (int)。
        目前只處理開倉方向 buy/sell，"close" 邏輯留到策略定案後再補
        （通常要另外查目前部位方向才能正確組出平倉單）。
        """
        if self._api is None:
            return OrderResult(ok=False, stage="order", errormsg="not logged in")

        order_obj = DOrderObject(
            actno=self.account,
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
