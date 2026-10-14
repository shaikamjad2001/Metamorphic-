"""Loop Supervisor sentry: enforces bounds on both cycles so neither loop can run away.

Invariants
  I1  cycle caps: <= MAX_FEEDBACK_CYCLES relaxations, <= MAX_REFINEMENT_CYCLES refinements
  I2  feedback monotonicity: each relaxation yields a superset scan, so coverage must not decrease
  I3  refinement progress: stop refining when a cycle fails to raise confidence
  I4  wall-clock budget for the whole run
"""
from __future__ import annotations

from backend import config
from backend.agents.base import Trace


class LoopSupervisor:
    name = "LoopSupervisor"

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self.coverage: list[float] = []
        self.confidence: list[float] = []
        self.halts: list[str] = []

    def _halt(self, loop: str, iteration: int, invariant: str, reason: str) -> bool:
        self.halts.append(f"{invariant}: {reason}")
        self.trace.log(self.name, "halted_loop", loop=loop, iteration=iteration, invariant=invariant, reason=reason)
        return False

    def _clock_ok(self) -> bool:
        return self.trace.elapsed_s() < config.WALL_CLOCK_BUDGET_S

    def record_coverage(self, coverage: float) -> None:
        self.coverage.append(coverage)

    def approve_feedback(self, next_iteration: int) -> bool:
        if next_iteration > config.MAX_FEEDBACK_CYCLES:
            return self._halt("feedback", next_iteration, "I1", f"feedback cap {config.MAX_FEEDBACK_CYCLES} reached")
        if len(self.coverage) >= 2 and self.coverage[-1] < self.coverage[-2] - 1e-12:
            return self._halt("feedback", next_iteration, "I2",
                              f"coverage fell {self.coverage[-2]:.3f} -> {self.coverage[-1]:.3f}")
        if not self._clock_ok():
            return self._halt("feedback", next_iteration, "I4", "wall-clock budget exhausted")
        self.trace.log(self.name, "approved_cycle", loop="feedback", iteration=next_iteration,
                       coverage_history=[round(c, 4) for c in self.coverage])
        return True

    def record_confidence(self, confidence: float) -> None:
        self.confidence.append(confidence)

    def approve_refinement(self, next_cycle: int) -> bool:
        if next_cycle > config.MAX_REFINEMENT_CYCLES:
            return self._halt("refinement", next_cycle, "I1", f"refinement cap {config.MAX_REFINEMENT_CYCLES} reached")
        if len(self.confidence) >= 2 and self.confidence[-1] <= self.confidence[-2] + 1e-9:
            return self._halt("refinement", next_cycle, "I3",
                              f"no confidence gain ({self.confidence[-2]:.4f} -> {self.confidence[-1]:.4f})")
        if not self._clock_ok():
            return self._halt("refinement", next_cycle, "I4", "wall-clock budget exhausted")
        self.trace.log(self.name, "approved_cycle", loop="refinement", iteration=next_cycle,
                       confidence_history=[round(c, 4) for c in self.confidence])
        return True
