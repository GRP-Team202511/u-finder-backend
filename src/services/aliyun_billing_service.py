# This code was completed by GRP Team 2025.11.
"""
Alibaba Cloud Billing Service
Fetches LLM cost data from Alibaba Cloud BSS OpenAPI (DescribeInstanceBill).

Billing data is delayed ~24 hours from actual consumption.
Reference: https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describeinstancebill
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Optional

from alibabacloud_bssopenapi20171214.client import Client as BssOpenApiClient
from alibabacloud_bssopenapi20171214 import models as bss_models
from alibabacloud_tea_openapi import models as open_api_models

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class AliyunDailyCost:
    """Aggregated cost for a single day from Alibaba Cloud billing."""
    billing_date: str
    total_pretax_amount: float  # 应付金额 (CNY)
    total_requests: int  # number of billing items
    currency: str  # CNY / USD


def _create_client() -> BssOpenApiClient:
    """Create an authenticated BSS OpenAPI client."""
    config = open_api_models.Config(
        access_key_id=settings.aliyun_access_key_id,
        access_key_secret=settings.aliyun_access_key_secret,
    )
    config.endpoint = "business.aliyuncs.com"
    return BssOpenApiClient(config)


def _sync_get_daily_cost(target_date: date) -> AliyunDailyCost:
    """Synchronous implementation — called via asyncio.to_thread()."""
    billing_cycle = target_date.strftime("%Y-%m")
    billing_date_str = target_date.isoformat()

    client = _create_client()

    total_amount = 0.0
    total_items = 0
    currency = "CNY"
    next_token: Optional[str] = None

    try:
        while True:
            request = bss_models.DescribeInstanceBillRequest(
                billing_cycle=billing_cycle,
                max_results=300,
                next_token=next_token,
            )

            response = client.describe_instance_bill(request)
            body = response.body

            if not body.success:
                logger.error("Alibaba billing API error: code=%s msg=%s",
                             body.code, body.message)
                break

            data = body.data
            if data and data.items:
                for item in data.items:
                    total_amount += float(item.pretax_amount or 0)
                    total_items += 1
                    if item.currency:
                        currency = item.currency

            if data and data.next_token:
                next_token = data.next_token
            else:
                break

    except Exception as exc:
        logger.error("Failed to fetch Alibaba Cloud billing: %s", exc)

    return AliyunDailyCost(
        billing_date=billing_date_str,
        total_pretax_amount=round(total_amount, 4),
        total_requests=total_items,
        currency=currency,
    )


async def get_daily_cost(
    target_date: date,
) -> AliyunDailyCost:
    """
    Query Alibaba Cloud DescribeInstanceBill for the month containing *target_date*.

    Only ``BillingCycle`` (YYYY-MM) is sent to the API; the response
    contains all items for that billing month.

    Args:
        target_date: A date within the billing month to query.

    Returns:
        AliyunDailyCost with aggregated totals for the billing month.
    """
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        logger.warning("Alibaba Cloud credentials not configured, returning zero cost")
        return AliyunDailyCost(
            billing_date=target_date.isoformat(),
            total_pretax_amount=0.0,
            total_requests=0,
            currency="CNY",
        )

    return await asyncio.to_thread(_sync_get_daily_cost, target_date)


def _sync_get_cost_by_date(target_date: date) -> AliyunDailyCost:
    """Synchronous implementation — called via asyncio.to_thread()."""
    billing_cycle = target_date.strftime("%Y-%m")
    billing_date_str = target_date.isoformat()
    client = _create_client()

    total_amount = 0.0
    total_items = 0
    currency = "CNY"
    next_token: Optional[str] = None

    try:
        while True:
            request = bss_models.DescribeInstanceBillRequest(
                billing_cycle=billing_cycle,
                billing_date=billing_date_str,
                granularity="DAILY",
                max_results=300,
                next_token=next_token,
            )

            response = client.describe_instance_bill(request)
            body = response.body

            if not body.success:
                logger.error("Alibaba daily billing API error: code=%s msg=%s",
                             body.code, body.message)
                break

            data = body.data
            if data and data.items:
                for item in data.items:
                    total_amount += float(item.pretax_amount or 0)
                    total_items += 1
                    if item.currency:
                        currency = item.currency

            if data and data.next_token:
                next_token = data.next_token
            else:
                break

    except Exception as exc:
        logger.error("Failed to fetch Alibaba Cloud daily billing: %s", exc)

    return AliyunDailyCost(
        billing_date=billing_date_str,
        total_pretax_amount=round(total_amount, 4),
        total_requests=total_items,
        currency=currency,
    )


async def get_cost_by_date(target_date: date) -> AliyunDailyCost:
    """Query Alibaba Cloud DescribeInstanceBill for a **single day**.

    Uses ``BillingCycle`` + ``BillingDate`` + ``Granularity=DAILY``
    (without ``ProductCode`` to avoid *ProductNotFind* errors).
    """
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        return AliyunDailyCost(
            billing_date=target_date.isoformat(),
            total_pretax_amount=0.0,
            total_requests=0,
            currency="CNY",
        )

    return await asyncio.to_thread(_sync_get_cost_by_date, target_date)
