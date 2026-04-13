from __future__ import annotations

from typing import Any

_WRAPPER_TO_VENUE = {
    "etf": "场内ETF",
    "stock": "场内股票",
    "fund": "场外基金",
    "cash_mgmt": "场外现金管理",
    "bond": "债券产品",
    "other": "其他产品",
}


def build_product_display(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    display_name = str(data.get("product_name") or "").strip() or None
    display_code = str(data.get("provider_symbol") or "").strip() or None
    wrapper_type = str(data.get("wrapper_type") or "other").strip()
    if wrapper_type not in _WRAPPER_TO_VENUE:
        raise KeyError(wrapper_type)
    trading_venue_label = _WRAPPER_TO_VENUE[wrapper_type]

    if display_name and display_code:
        display_label = f"{display_name} ({display_code}, {trading_venue_label})"
    elif display_name:
        display_label = f"{display_name} ({trading_venue_label})"
    elif display_code:
        display_label = f"{display_code} ({trading_venue_label})"
    else:
        display_label = trading_venue_label

    return {
        "display_name": display_name,
        "display_code": display_code,
        "trading_venue_label": trading_venue_label,
        "display_label": display_label,
    }
