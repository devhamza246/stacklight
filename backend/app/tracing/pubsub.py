"""In-process span event bus. The SSE stream subscribes per run_id."""
import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass

_QUEUE_SIZE = 256
_subs: dict[str, set["Subscription"]] = defaultdict(set)


@dataclass(frozen=True)
class SpanEvent:
    run_id: str
    span_id: str
    parent_id: str | None
    agent: str
    name: str
    status: str  # started | ok | error
    cost_usd: float = 0.0
    cost_known: bool = True
    latency_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    type: str = "span"

    def to_dict(self) -> dict:
        return asdict(self)


class Subscription:
    """Registered on creation; drop-oldest when the consumer is slow. Close it (or use
    `async with`) on disconnect."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._q: asyncio.Queue[SpanEvent] = asyncio.Queue(_QUEUE_SIZE)
        _subs[run_id].add(self)

    def _put(self, ev: SpanEvent) -> None:
        if self._q.full():
            self._q.get_nowait()
        self._q.put_nowait(ev)

    def close(self) -> None:
        _subs[self.run_id].discard(self)
        if not _subs[self.run_id]:
            del _subs[self.run_id]

    def __aiter__(self):
        return self

    async def __anext__(self) -> SpanEvent:
        return await self._q.get()

    async def aclose(self) -> None:
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.close()


def subscribe(run_id: str) -> Subscription:
    return Subscription(run_id)


def publish(ev: SpanEvent) -> None:
    for sub in list(_subs.get(ev.run_id, ())):
        sub._put(ev)
