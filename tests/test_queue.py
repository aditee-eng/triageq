import asyncio

import pytest

from app.queue import HEAD_START, QueueService, score_for

T0 = 1_800_000_000.0  # arbitrary "now"
MIN = 60.0


async def order(q: QueueService, dept="d"):
    return [v for v, _ in await q.list(dept)]


@pytest.fixture()
def q(redis):
    return QueueService(redis)


async def test_esi1_and_2_are_never_overtaken_even_after_a_ten_hour_wait(q):
    await q.add("d", "old_esi3", 3, T0 - 600 * MIN)  # waited 10 hours
    await q.add("d", "old_esi5", 5, T0 - 600 * MIN)
    await q.add("d", "new_esi2", 2, T0)
    await q.add("d", "new_esi1", 1, T0 + 60)
    assert await order(q) == ["new_esi1", "new_esi2", "old_esi3", "old_esi5"]


async def test_fifo_within_the_same_level(q):
    for i, name in enumerate(["a", "b", "c"]):
        await q.add("d", name, 3, T0 + i)
    assert await order(q) == ["a", "b", "c"]


@pytest.mark.parametrize("extra_wait_min, esi4_first", [(59, False), (61, True)])
async def test_esi4_overtakes_fresh_esi3_after_60_extra_minutes(q, extra_wait_min, esi4_first):
    await q.add("d", "esi4", 4, T0 - extra_wait_min * MIN)
    await q.add("d", "esi3", 3, T0)
    assert (await order(q))[0] == ("esi4" if esi4_first else "esi3")


async def test_esi5_overtakes_fresh_esi3_after_two_hours(q):
    await q.add("d", "esi5", 5, T0 - 121 * MIN)
    await q.add("d", "esi3", 3, T0)
    assert (await order(q))[0] == "esi5"


def test_head_starts_are_strictly_decreasing():
    levels = [HEAD_START[i] for i in range(1, 6)]
    assert levels == sorted(levels, reverse=True) and len(set(levels)) == 5


async def test_pop_returns_head_and_score_and_empty_returns_none(q):
    await q.add("d", "a", 3, T0)
    vid, score = await q.pop_next("d")
    assert vid == "a" and score == score_for(3, T0)
    assert await q.pop_next("d") is None


async def test_100_concurrent_pops_never_return_the_same_visit(q):
    for i in range(50):
        await q.add("d", f"v{i}", 3, T0 + i)
    results = await asyncio.gather(*(q.pop_next("d") for _ in range(100)))
    got = [r[0] for r in results if r is not None]
    assert len(got) == 50 and len(set(got)) == 50  # all served exactly once
    assert results.count(None) == 50


async def test_update_priority_keeps_arrival_time_and_never_resurrects(q):
    await q.add("d", "a", 4, T0)
    await q.add("d", "b", 4, T0 + 10)
    assert await q.update_priority("d", "b", 2, T0 + 10)  # escalated: now first
    assert await order(q) == ["b", "a"]
    await q.remove("d", "b")
    assert not await q.update_priority("d", "b", 1, T0)  # XX: removed visit stays removed
    assert await order(q) == ["a"]


async def test_position_is_one_based_and_none_when_absent(q):
    await q.add("d", "a", 3, T0)
    await q.add("d", "b", 3, T0 + 1)
    assert await q.position("d", "a") == 1 and await q.position("d", "b") == 2
    assert await q.position("d", "zzz") is None
