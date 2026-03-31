# This code was completed by GRP Team 2025.11.
"""
Tencent Cloud Billing Service
Fetches LLM cost data from Tencent Cloud DescribeBillDetail API.

The DescribeBillDetail API always returns **entire-month** data regardless
of BeginTime/EndTime values.  We use the ``Month`` parameter for simplicity
and filter by ``BillDay`` when per-day granularity is needed.

Reference: https://cloud.tencent.com/document/api/555/19182
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from tencentcloud.common import credential
from tencentcloud.billing.v20180709 import billing_client, models

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class TencentDailyCost:
    """Aggregated cost from Tencent Cloud billing."""
    billing_date: str
    total_real_cost: float  # 实际花费 (CNY)
    total_items: int
    currency: str  # CNY


def _create_client() -> billing_client.BillingClient:
    """Create an authenticated Tencent Cloud billing client."""
    cred = credential.Credential(
        settings.tencent_secret_id,
        settings.tencent_secret_key,
    )
    return billing_client.BillingClient(cred, "")


def _empty_cost(target_date: date) -> TencentDailyCost:
    return TencentDailyCost(
        billing_date=target_date.isoformat(),
        total_real_cost=0.0,
        total_items=0,
        currency="CNY",
    )


def _fetch_month_details(
    target_date: date,
    product_code: Optional[str] = None,
) -> list:
    """Fetch all BillDetail items for the month containing *target_date*.

    Returns a list of raw BillDetail objects from the SDK.
    """
    if not settings.tencent_secret_id or not settings.tencent_secret_key:
        return []

    product = product_code or settings.tencent_billing_product_code
    month = target_date.strftime("%Y-%m")
    client = _create_client()

    all_items: list = []
    offset = 0
    limit = 300
    context: Optional[str] = None

    try:
        while True:
            req = models.DescribeBillDetailRequest()
            params: dict = {
                "Offset": offset,
                "Limit": limit,
                "Month": month,
                "NeedRecordNum": 1,
            }
            if product:
                params["BusinessCode"] = product
            if context:
                params["Context"] = context
            req.from_json_string(json.dumps(params))

            resp = client.DescribeBillDetail(req)

            if resp.DetailSet:
                all_items.extend(resp.DetailSet)

            if resp.Context:
                context = resp.Context

            total_count = resp.Total or 0
            offset += limit
            if offset >= total_count:
                break

    except Exception as exc:
        logger.error("Failed to fetch Tencent Cloud billing: %s", exc)

    return all_items


def _aggregate_items(items: list, label: str) -> TencentDailyCost:
    """Sum RealCost across all ComponentSet entries."""
    total_cost = 0.0
    total_items = 0
    for detail in items:
        if detail.ComponentSet:
            for comp in detail.ComponentSet:
                total_cost += float(comp.RealCost or 0)
        total_items += 1
    return TencentDailyCost(
        billing_date=label,
        total_real_cost=round(total_cost, 4),
        total_items=total_items,
        currency="CNY",
    )


async def get_daily_cost(
    target_date: date,
    product_code: Optional[str] = None,
) -> TencentDailyCost:
    """Return **entire-month** cost for the month containing *target_date*.

    Used by the LLM Cost (This Month) summary card.
    """
    if not settings.tencent_secret_id or not settings.tencent_secret_key:
        logger.warning("Tencent Cloud credentials not configured, returning zero cost")
        return _empty_cost(target_date)

    items = _fetch_month_details(target_date, product_code)
    result = _aggregate_items(items, target_date.isoformat())
    return result


async def get_cost_by_date(
    target_date: date,
    product_code: Optional[str] = None,
) -> TencentDailyCost:
    """Return cost for a **single day** by filtering on ``BillDay``.

    The API returns entire-month data; we filter items whose ``BillDay``
    matches *target_date*.
    """
    if not settings.tencent_secret_id or not settings.tencent_secret_key:
        return _empty_cost(target_date)

    target_str = target_date.isoformat()  # "2026-03-30"
    all_items = _fetch_month_details(target_date, product_code)

    # BillDay format: "2026-03-30 00:00:00"
    day_items = [
        d for d in all_items
        if getattr(d, "BillDay", "") and d.BillDay[:10] == target_str
    ]

    return _aggregate_items(day_items, target_str)
