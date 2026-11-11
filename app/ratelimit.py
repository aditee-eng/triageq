"""Login brute-force protection (Redis fixed-window counters).

Three counters so one attacker cannot lock a victim out of their own account:
  - per (email, ip): 5 failures / 15 min   -> stops guessing from one place
  - per ip:         30 failures / 15 min   -> stops one machine spraying many accounts
  - per email:      50 failures / 15 min   -> stops a distributed attack on one account
Fails OPEN if Redis is down (a hospital must still be able to log in); the failure is logged.
"""
import logging

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)
WINDOW_SECONDS = 900
LIMITS = {"pair": 5, "ip": 30, "email": 50}


def _keys(email: str, ip: str) -> dict[str, str]:
    return {
        "pair": f"rl:login:pair:{email}|{ip}",
        "ip": f"rl:login:ip:{ip}",
        "email": f"rl:login:email:{email}",
    }


async def ensure_not_locked(redis: Redis, email: str, ip: str) -> None:
    try:
        for name, key in _keys(email, ip).items():
            count = await redis.get(key)
            if count is not None and int(count) >= LIMITS[name]:
                ttl = await redis.ttl(key)
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many failed login attempts. Try again later.",
                    headers={"Retry-After": str(max(ttl, 1))},
                )
    except RedisError:
        log.warning("rate limiter unavailable (Redis down); failing open")


async def record_failure(redis: Redis, email: str, ip: str) -> None:
    try:
        for key in _keys(email, ip).values():
            pipe = redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS, nx=True)  # set TTL only on first hit, atomically
            await pipe.execute()
    except RedisError:
        log.warning("rate limiter unavailable (Redis down); failure not counted")


async def record_success(redis: Redis, email: str, ip: str) -> None:
    try:
        await redis.delete(_keys(email, ip)["pair"])
    except RedisError:
        pass
