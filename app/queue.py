"""Redis priority queues. Postgres stays the source of truth; Redis only holds ordering.

Aging without a background job
------------------------------
Each waiting visit is a member of a sorted set `queue:<department>` with

    score = checked_in_epoch_seconds - HEAD_START[esi_level]

Lowest score is served first. A higher-urgency level gets a bigger "head start", so it is
served first, but a patient who has waited long enough still overtakes newer, more urgent
ones: ESI 4 overtakes a fresh ESI 3 once it has waited 60 min longer, ESI 5 overtakes
ESI 4 after 60 more. ESI 1 and 2 get head starts of years, so they are never overtaken.
Scores never change as time passes, so there is no re-ranking worker and no race with one.
"""
from redis.asyncio import Redis

HEAD_START: dict[int, int] = {
    1: 300_000_000,  # ~9.5 years: strict priority
    2: 200_000_000,  # ~6.3 years: strict priority
    3: 7_200,  # 120 min
    4: 3_600,  # 60 min
    5: 0,
}


def queue_key(dept_code: str) -> str:
    return f"queue:{dept_code}"


def score_for(esi_level: int, checked_in_epoch: float) -> float:
    return checked_in_epoch - HEAD_START[esi_level]


class QueueService:
    def __init__(self, redis: Redis):
        self.r = redis

    async def add(self, dept: str, visit_id: str, esi_level: int, checked_in_epoch: float) -> None:
        await self.r.zadd(queue_key(dept), {visit_id: score_for(esi_level, checked_in_epoch)})

    async def restore(self, dept: str, visit_id: str, score: float) -> None:
        """Put back a popped entry with its original score (used when the DB step fails)."""
        await self.r.zadd(queue_key(dept), {visit_id: score})

    async def update_priority(self, dept: str, visit_id: str, esi_level: int, checked_in_epoch: float) -> bool:
        """Change priority but keep the original arrival time. XX: never re-adds a removed visit."""
        changed = await self.r.zadd(
            queue_key(dept), {visit_id: score_for(esi_level, checked_in_epoch)}, xx=True, ch=True
        )
        return bool(changed)

    async def pop_next(self, dept: str) -> tuple[str, float] | None:
        """Atomic: ZPOPMIN is a single Redis command, so two callers can never get the same visit."""
        popped = await self.r.zpopmin(queue_key(dept), 1)
        return (popped[0][0], popped[0][1]) if popped else None

    async def remove(self, dept: str, visit_id: str) -> None:
        await self.r.zrem(queue_key(dept), visit_id)

    async def position(self, dept: str, visit_id: str) -> int | None:
        rank = await self.r.zrank(queue_key(dept), visit_id)
        return None if rank is None else rank + 1

    async def length(self, dept: str) -> int:
        return await self.r.zcard(queue_key(dept))

    async def list(self, dept: str, limit: int = 100) -> list[tuple[str, float]]:
        return await self.r.zrange(queue_key(dept), 0, limit - 1, withscores=True)

    async def members(self, dept: str) -> set[str]:
        return set(await self.r.zrange(queue_key(dept), 0, -1))
