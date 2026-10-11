"""Who may talk to the model right now.

Up to max_parallel runs at once, all on the same model setup (name and context size). A run for a
different setup waits until the current ones are done, because loading another model (or the same
one with another context size) makes Ollama unload and reload, which is far slower than waiting.
Waiting runs are served strictly in arrival order, so nobody starves, and each can be told its
place in line. A run that is stopped or disconnected while waiting simply leaves the line.

Waiting runs look at the line every few milliseconds instead of sleeping on an asyncio primitive, so the
scheduler works from any event loop (the test client runs every websocket in a loop of its own)."""
from __future__ import annotations

import asyncio
import itertools
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

_ids = itertools.count(1)


@dataclass(eq=False)
class Ticket:
    model: str  # what must be loaded, for example "qwen3:8b@8192"
    id: int = field(default_factory=lambda: next(_ids))


class Cancelled(Exception):
    """The run left the line before it got a slot (Stop pressed, or the page went away)."""


class ModelScheduler:
    def __init__(self, max_parallel: int = 1) -> None:
        self.max_parallel = max_parallel
        self.active: dict[str, int] = {}  # model setup -> runs in flight
        self.waiting: list[Ticket] = []
        self.version = 0  # goes up whenever the line or the slots change

    # ---------- state ----------

    @property
    def running(self) -> int:
        return sum(self.active.values())

    def busy(self) -> bool:
        """True when a new run would have to wait."""
        return bool(self.waiting) or self.running >= self.max_parallel

    def position(self, ticket: Ticket) -> int:
        """1 for the next in line."""
        return self.waiting.index(ticket) + 1 if ticket in self.waiting else 0

    def _can_start(self, ticket: Ticket) -> bool:
        if not self.waiting or self.waiting[0] is not ticket:
            return False  # strictly first come, first served
        if self.running >= self.max_parallel:
            return False
        return not self.active or set(self.active) == {ticket.model}

    def _reason(self, ticket: Ticket) -> str:
        if self.active and set(self.active) != {ticket.model} and self.running < self.max_parallel:
            return "model"  # a slot is free, but another model is loaded
        return "slots"

    def _notify(self) -> None:
        self.version += 1

    # ---------- taking and giving back a slot ----------

    async def acquire(self, model: str, on_wait: Callable[[int, str], Awaitable[None]] | None = None,
                      should_stop: Callable[[], bool] | None = None, poll: float = 0.05) -> Ticket:
        """Wait for a slot. on_wait(position, reason) is called whenever the place in line changes;
        reason is "slots" (all slots busy) or "model" (another model is loaded)."""
        ticket = Ticket(model)
        self.waiting.append(ticket)
        told = None
        try:
            while not self._can_start(ticket):
                if should_stop and should_stop():
                    raise Cancelled()
                place = (self.position(ticket), self._reason(ticket))
                if on_wait and place != told:
                    told = place
                    await on_wait(*place)
                    continue  # the line may have moved while we were telling
                await asyncio.sleep(poll)
        except BaseException:
            if ticket in self.waiting:
                self.waiting.remove(ticket)
                self._notify()
            raise
        self.waiting.remove(ticket)
        self.active[model] = self.active.get(model, 0) + 1
        self._notify()
        return ticket

    def release(self, ticket: Ticket) -> None:
        left = self.active.get(ticket.model, 0) - 1
        if left > 0:
            self.active[ticket.model] = left
        else:
            self.active.pop(ticket.model, None)
        self._notify()

    @asynccontextmanager
    async def slot(self, model: str, **kwargs) -> AsyncIterator[Ticket]:
        ticket = await self.acquire(model, **kwargs)
        try:
            yield ticket
        finally:
            self.release(ticket)  # always, even when the run failed
