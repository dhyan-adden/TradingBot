from dataclasses import dataclass
from typing import Literal


Product = Literal["CNC", "MIS"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    stamp: float
    gst: float
    dp: float
    total: float


def estimate_cost(
    side: Side,
    product: Product,
    quantity: int,
    price: float,
    cnc_brokerage_inr: float = 0,
    mis_brokerage_inr_max: float = 20,
    mis_brokerage_pct: float = 0.0003,
    stt_sell_cnc_pct: float = 0.001,
    stt_sell_mis_pct: float = 0.00025,
    stamp_buy_cnc_pct: float = 0.00015,
    stamp_buy_mis_pct: float = 0.00003,
    gst_pct: float = 0.18,
    dp_charge_inr_per_scrip: float = 15.93,
) -> CostBreakdown:
    turnover = max(0.0, quantity * price)
    if product == "CNC":
        brokerage = cnc_brokerage_inr
        stt = turnover * stt_sell_cnc_pct if side == "SELL" else 0.0
        stamp = turnover * stamp_buy_cnc_pct if side == "BUY" else 0.0
        dp = dp_charge_inr_per_scrip if side == "SELL" else 0.0
    else:
        brokerage = min(mis_brokerage_inr_max, turnover * mis_brokerage_pct)
        stt = turnover * stt_sell_mis_pct if side == "SELL" else 0.0
        stamp = turnover * stamp_buy_mis_pct if side == "BUY" else 0.0
        dp = 0.0
    gst = brokerage * gst_pct
    total = brokerage + stt + stamp + gst + dp
    return CostBreakdown(round(brokerage, 2), round(stt, 2), round(stamp, 2), round(gst, 2), round(dp, 2), round(total, 2))
