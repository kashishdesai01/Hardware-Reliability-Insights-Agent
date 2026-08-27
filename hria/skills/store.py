from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from hria.skills.contracts import ToolResult


class ResultStore:
    def __init__(self, maximum_results: int = 1_000) -> None:
        self._maximum_results = maximum_results
        self._items: OrderedDict[str, ToolResult] = OrderedDict()
        self._lock = Lock()

    def put(self, result: ToolResult) -> None:
        provenance = getattr(result, "provenance", None)
        if provenance is None:
            return
        with self._lock:
            self._items[provenance.result_id] = result
            self._items.move_to_end(provenance.result_id)
            while len(self._items) > self._maximum_results:
                self._items.popitem(last=False)

    def get(self, result_id: str) -> ToolResult | None:
        with self._lock:
            result = self._items.get(result_id)
            if result is not None:
                self._items.move_to_end(result_id)
            return result


result_store = ResultStore()
