"""
UniTrade API 封裝骨架。

架構決策：login-per-request —— 每次呼叫都是 login() → 下單 → logout()，
不維持長連線（見 repo README 架構決策 #1）。

參考文件：https://pfcec.github.io/unitrade/開始/
登入需要：伺服器網址、交易帳號、交易密碼、憑證檔(.pfx)路徑、憑證密碼。
這些一律從 Secret Manager 取得，不寫死在程式碼或 repo 裡。

尚未實作 —— 等簡單策略定案後補上。
"""
from dataclasses import dataclass


@dataclass
class OrderResult:
    ok: bool
    order_id: str = ""
    errorcode: str = ""
    errormsg: str = ""


class UnitradeClient:
    def __init__(self, url: str, account: str, password: str, cert_path: str, cert_password: str):
        self.url = url
        self.account = account
        self.password = password
        self.cert_path = cert_path
        self.cert_password = cert_password
        self._api = None

    def login(self) -> bool:
        # TODO: import unitrade; self._api = unitrade.Unitrade(); self._api.login(...)
        raise NotImplementedError

    def place_order(self, signal: dict) -> OrderResult:
        # TODO: 依 signal["symbol"] / signal["action"] / signal["qty"] 組出下單參數並呼叫 SDK
        raise NotImplementedError

    def logout(self) -> None:
        # TODO: 呼叫 SDK 的登出/斷線方法
        raise NotImplementedError
