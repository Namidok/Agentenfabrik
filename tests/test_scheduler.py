"""The model scheduler: parallel slots, one model setup at a time, a fair line, Stop while waiting."""
import asyncio

import pytest

from factory.scheduler import Cancelled, ModelScheduler


def run(coro):
    return asyncio.run(coro)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def test_two_runs_of_the_same_model_share_two_slots_and_a_third_waits_in_line():
    async def main():
        s = ModelScheduler(2)
        a = await s.acquire("m")
        b = await s.acquire("m")
        told = []

        async def tell(pos, why):
            told.append((pos, why))
        third = asyncio.create_task(s.acquire("m", on_wait=tell, poll=0.01))
        await settle()
        assert not third.done() and told == [(1, "slots")] and s.running == 2
        s.release(a)
        c = await asyncio.wait_for(third, 1)
        assert s.running == 2
        for t in (b, c):
            s.release(t)
        assert s.running == 0 and not s.busy()
    run(main())


def test_another_model_waits_for_the_loaded_one_to_finish_instead_of_swapping():
    async def main():
        s = ModelScheduler(3)
        first = await s.acquire("big@8192")
        told = []

        async def tell(pos, why):
            told.append(why)
        other = asyncio.create_task(s.acquire("small@4096", on_wait=tell, poll=0.01))
        await settle()
        assert not other.done() and told == ["model"]  # a slot is free, but the model is not
        s.release(first)
        ticket = await asyncio.wait_for(other, 1)
        assert s.active == {"small@4096": 1}
        s.release(ticket)
    run(main())


def test_the_line_is_first_come_first_served():
    async def main():
        s = ModelScheduler(2)
        busy = await s.acquire("a")
        other_model = asyncio.create_task(s.acquire("b", poll=0.01))
        await settle()
        same_model = asyncio.create_task(s.acquire("a", poll=0.01))
        await settle()
        assert not same_model.done()  # a slot is free for "a", but "b" came first
        assert s.position(s.waiting[1]) == 2
        s.release(busy)
        b = await asyncio.wait_for(other_model, 1)
        await settle()
        assert not same_model.done()  # "b" is loaded now, so "a" still waits
        s.release(b)
        s.release(await asyncio.wait_for(same_model, 1))
    run(main())


def test_stop_while_waiting_leaves_the_line_and_the_next_one_moves_up():
    async def main():
        s = ModelScheduler(1)
        busy = await s.acquire("m")
        stop = {"now": False}
        positions = []

        async def tell(pos, why):
            positions.append(pos)
        stopped = asyncio.create_task(s.acquire("m", should_stop=lambda: stop["now"], poll=0.01))
        await settle()
        later = asyncio.create_task(s.acquire("m", on_wait=tell, poll=0.01))
        await settle()
        assert positions == [2]
        stop["now"] = True
        with pytest.raises(Cancelled):
            await asyncio.wait_for(stopped, 1)
        await asyncio.sleep(0.05)
        assert positions == [2, 1] and len(s.waiting) == 1
        s.release(busy)
        s.release(await asyncio.wait_for(later, 1))
    run(main())


def test_a_failing_run_gives_its_slot_back():
    async def main():
        s = ModelScheduler(1)
        with pytest.raises(RuntimeError):
            async with s.slot("m"):
                raise RuntimeError("the model crashed")
        assert s.running == 0
        async with s.slot("m"):
            assert s.running == 1
    run(main())


def test_a_waiter_that_is_cancelled_does_not_block_the_line():
    async def main():
        s = ModelScheduler(1)
        busy = await s.acquire("m")
        gone = asyncio.create_task(s.acquire("m", poll=0.01))
        await settle()
        gone.cancel()
        await asyncio.sleep(0.02)
        assert s.waiting == []
        s.release(busy)
        s.release(await asyncio.wait_for(s.acquire("m"), 1))
    run(main())
