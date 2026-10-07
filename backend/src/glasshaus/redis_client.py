"""Shared Redis client (cache, pub/sub; arq uses its own pool)."""

from functools import lru_cache

from redis.asyncio import Redis

from glasshaus.config import get_settings


@lru_cache
def get_redis() -> Redis:
    client: Redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return client


async def ping_redis() -> None:
    await get_redis().ping()
