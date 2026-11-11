from fastapi import Depends
from redis.asyncio import Redis

from app.config import settings
from app.queue import QueueService

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> Redis:
    return redis_client


async def get_queues(redis: Redis = Depends(get_redis)) -> QueueService:
    return QueueService(redis)
