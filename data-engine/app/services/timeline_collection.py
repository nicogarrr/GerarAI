"""Bounded timeline collection, preserving total eligible event count."""
from heapq import heappush, heappushpop
from typing import Any


class TimelineEvents(list[dict[str, Any]]):
    """List-compatible result; total counts eligible events before the cap."""

    def __init__(self, events: list[dict[str, Any]], total: int):
        super().__init__(events)
        self.total = total
        self.truncated = total > len(events)


class TimelineCollector:
    def __init__(self, limit: int):
        self.limit = limit
        self.total = 0
        self._heap: list[tuple[str, str, dict[str, Any]]] = []

    def append(self, event: dict[str, Any]) -> None:
        # IDs are unique across persisted event types. Retain the exact
        # previous ordering (ISO day, lexical ID), not timestamp ordering.
        self.total += 1
        entry = (event['date'], event['id'], event)
        if len(self._heap) < self.limit:
            heappush(self._heap, entry)
        else:
            heappushpop(self._heap, entry)

    def result(self) -> TimelineEvents:
        return TimelineEvents([entry[2] for entry in sorted(self._heap, reverse=True)], self.total)
