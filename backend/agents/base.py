from __future__ import annotations

import time
from typing import Any, Optional

from backend.schemas import AgentEvent


class Trace:
    """Append-only execution log shared by all agents in one run."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []
        self._t0 = time.perf_counter()

    def elapsed_s(self) -> float:
        return time.perf_counter() - self._t0

    def log(self, agent: str, action: str, loop: Optional[str] = None, iteration: Optional[int] = None,
            **detail: Any) -> None:
        self.events.append(AgentEvent(step=len(self.events) + 1, agent=agent, action=action, loop=loop,
                                      iteration=iteration, detail=detail,
                                      elapsed_ms=round(self.elapsed_s() * 1000, 2)))
