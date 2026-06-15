"""Optional per-module debug payloads on request.state for agentic modules."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from state import request as request_state

DEBUG_SUFFIX = "_debug"


class ModuleDebug(BaseModel):
  triggered: bool = False
  skipped: bool = True
  reason: str = ""
  duration_ms: int = 0
  extra_calls: int = 0
  extra: dict[str, Any] = Field(default_factory=dict)


class DebugTimer:
  """Wall-clock timer for module apply() duration_ms."""

  def __init__(self) -> None:
    self._start = time.perf_counter()

  def elapsed_ms(self) -> int:
    return int((time.perf_counter() - self._start) * 1000)


def state_key(module_id: str) -> str:
  return f"{module_id}{DEBUG_SUFFIX}"


def _request_state():
  request = request_state.get()
  if request is None:
    return None
  return request.state


def record(module_id: str, payload: ModuleDebug | dict[str, Any]) -> ModuleDebug | None:
  """Write a debug payload to request.state; returns None when no request context."""
  state = _request_state()
  if state is None:
    return None

  debug = payload if isinstance(payload, ModuleDebug) else ModuleDebug(**payload)
  setattr(state, state_key(module_id), debug.model_dump())
  return debug


def get(module_id: str) -> ModuleDebug | None:
  """Read a module debug payload from request.state."""
  state = _request_state()
  if state is None:
    return None

  raw = getattr(state, state_key(module_id), None)
  if raw is None:
    return None
  if isinstance(raw, ModuleDebug):
    return raw
  return ModuleDebug(**raw)


def skipped_payload(
  reason: str,
  *,
  duration_ms: int = 0,
  extra_calls: int = 0,
  **extra: Any,
) -> ModuleDebug:
  return ModuleDebug(
    triggered=False,
    skipped=True,
    reason=reason,
    duration_ms=duration_ms,
    extra_calls=extra_calls,
    extra=extra,
  )


def triggered_payload(
  reason: str = "triggered",
  *,
  duration_ms: int = 0,
  extra_calls: int = 0,
  **extra: Any,
) -> ModuleDebug:
  return ModuleDebug(
    triggered=True,
    skipped=False,
    reason=reason,
    duration_ms=duration_ms,
    extra_calls=extra_calls,
    extra=extra,
  )