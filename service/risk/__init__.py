"""
風控規則骨架。任何下單前都要先過這裡，任何一項不通過就整單擋下並記錄原因。

尚未實作 —— 等簡單策略定案、確認商品/資金規模後補上真正的門檻值。
規劃中的檢查項目：
    - 單筆/單日最大部位（max position size / max daily volume）
    - 每日最大虧損停損（daily loss kill switch，可從外部一鍵關閉交易）
    - 交易時段檢查（含 UniTrade 系統維護時段）
    - 重複/衝突訊號檢查（同方向重複訊號、與現有部位方向衝突）
"""
from dataclasses import dataclass


@dataclass
class RiskCheckResult:
    ok: bool
    reason: str = ""


def check_order(signal: dict) -> RiskCheckResult:
    """TODO: 實作風控規則。目前一律通過（僅供打通 pipeline 用，不可上線）。"""
    return RiskCheckResult(ok=True)
