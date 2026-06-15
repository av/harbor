"""Optional per-module debug payloads on request.state for agentic modules."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

import config as boost_config
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


def _truthy(value: Any) -> bool:
  if value is None:
    return False
  if isinstance(value, bool):
    return value
  return str(value).strip().lower() in {"1", "true", "yes", "on"}


def debug_enabled(llm) -> bool:
  """Return True when debug metrics should appear in the final status."""
  value = llm.boost_params.get("debug")
  if value is not None:
    return _truthy(value)
  return boost_config.BOOST_DEBUG.value


def collect_all() -> dict[str, dict[str, Any]]:
  """Return all module debug payloads stored on request.state."""
  state = _request_state()
  if state is None:
    return {}

  payloads: dict[str, dict[str, Any]] = {}
  for key, value in vars(state).items():
    if not key.endswith(DEBUG_SUFFIX):
      continue
    module_id = key[: -len(DEBUG_SUFFIX)]
    if isinstance(value, ModuleDebug):
      payloads[module_id] = value.model_dump()
    elif isinstance(value, dict):
      payloads[module_id] = value
  return dict(sorted(payloads.items()))


def _format_extra_value(value: Any) -> str:
  text = str(value)
  if len(text) > 24:
    return text[:21] + "..."
  return text


def format_module_line(module_id: str, data: dict[str, Any]) -> str:
  """Compact one-line summary for a single module debug payload."""
  verb = "skipped" if data.get("skipped") else "triggered"
  parts = [module_id, verb]
  reason = (data.get("reason") or "").strip()
  if reason and reason != "triggered":
    parts.append(f"({reason})")
  parts.append(f"{data.get('duration_ms', 0)}ms")
  calls = data.get("extra_calls") or 0
  if calls:
    parts.append(f"+{calls}calls")
  extra = data.get("extra") or {}
  if extra:
    extras = ",".join(
      f"{key}={_format_extra_value(val)}"
      for key, val in sorted(extra.items())
    )
    parts.append(f"[{extras}]")
  return " ".join(parts)


def format_compact_summary(payloads: dict[str, dict[str, Any]]) -> str:
  """Render all module debug payloads as a compact status line."""
  if not payloads:
    return ""
  lines = [format_module_line(module_id, data) for module_id, data in payloads.items()]
  return "Debug: " + " | ".join(lines)


def final_status_summary(llm) -> str | None:
  """Build the final emit_status debug summary when debug mode is enabled."""
  if not debug_enabled(llm):
    return None
  summary = format_compact_summary(collect_all())
  return summary or None