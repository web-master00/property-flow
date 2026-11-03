"""Cache helpers for dashboard summaries."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: int | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """Get a tenant-scoped revenue summary, bypassing Redis when unavailable."""
    cache_key = f"revenue:v2:{tenant_id}:{property_id}:{year or 'latest'}:{month or 'latest'}"

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except (RedisError, json.JSONDecodeError, TypeError):
        logger.warning("Revenue cache read failed; falling back to the database", exc_info=True)

    from app.services.reservations import calculate_total_revenue

    result = await calculate_total_revenue(
        property_id, tenant_id, month=month, year=year
    )

    try:
        await redis_client.setex(cache_key, 300, json.dumps(result))
    except RedisError:
        logger.warning("Revenue cache write failed", exc_info=True)

    return result
