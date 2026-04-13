from __future__ import annotations

_WRAPPER_TO_VENUE = {
    "etf": "场内ETF",
    "stock": "场内股票",
    "fund": "场外基金",
    "cash_mgmt": "场外现金管理",
    "bond": "债券产品",
    "other": "其他产品",
}


def build_product_display(payload):
    display_name = str(payload.get("product_name") or "").strip()
    display_code = str(payload.get("provider_symbol") or "").strip()
    wrapper_type = str(payload.get("wrapper_type") or "other").strip()
    trading_venue_label = _WRAPPER_TO_VENUE[wrapper_type]
    display_label = f"{display_name} ({display_code}, {trading_venue_label})"

    return {
        "display_name": display_name,
        "display_code": display_code,
        "trading_venue_label": trading_venue_label,
        "display_label": display_label,
    }
