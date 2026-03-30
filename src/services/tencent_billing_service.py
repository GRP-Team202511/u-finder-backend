"""
Tencent Cloud Billing Service
Fetches LLM cost data from Tencent Cloud DescribeBillDetail API.

Reference: https://cloud.tencent.com/document/product/555/19182
"""
from __future__ import annotations

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
    """Aggregated cost for a single day from Tencent Cloud billing."""
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


async def get_daily_cost(
    target_date: date,
    product_code: Optional[str] = None,
) -> TencentDailyCost:
    """
    Query Tencent Cloud DescribeBillDetail for a specific day.

    The API requires BeginTime+EndTime within the same month.
    We query for the single target_date day.

    Args:
        target_date: The billing date to query (YYYY-MM-DD).
        product_code: Tencent Cloud BusinessCode to filter
                      (e.g. "p_hunyuanturbo"). Defaults to settings value.

    Returns:
        TencentDailyCost with aggregated totals for that day.
    """
    if not settings.tencent_secret_id or not settings.tencent_secret_key:
        logger.warning("Tencent Cloud credentials not configured, returning zero cost")
        return TencentDailyCost(
            billing_date=target_date.isoformat(),
            total_real_cost=0.0,
            total_items=0,
            currency="CNY",
        )

    product = product_code or settings.tencent_billing_product_code
    begin_time = f"{target_date.isoformat()} 00:00:00"
    end_time = f"{target_date.isoformat()} 23:59:59"

    client = _create_client()

    total_cost = 0.0
    total_items = 0
    offset = 0
    limit = 300

    try:
        while True:
            req = models.DescribeBillDetailRequest()
            params = {
                "Offset": offset,
                "Limit": limit,
                "BeginTime": begin_time,
                "EndTime": end_time,
                "NeedRecordNum": 1,
            }
            if product:
                params["BusinessCode"] = product
            req.from_json_string(
                __import__("json").dumps(params)
            )

            resp = client.DescribeBillDetail(req)

            if resp.DetailSet:
                for detail in resp.DetailSet:
                    # Each detail has ComponentSet with cost breakdowns
                    if detail.ComponentSet:
                        for comp in detail.ComponentSet:
                            cost = float(comp.RealCost or 0)
                            total_cost += cost
                    total_items += 1

            total_count = resp.Total or 0
            offset += limit
            if offset >= total_count:
                break

    except Exception as exc:
        logger.error("Failed to fetch Tencent Cloud billing: %s", exc)

    return TencentDailyCost(
        billing_date=target_date.isoformat(),
        total_real_cost=round(total_cost, 4),
        total_items=total_items,
        currency="CNY",
    )
