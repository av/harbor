"""Tests for optional agentic module debug payloads on request.state."""

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import autocheck, caveman
from research import debug_metrics
from research.brief import ResearchBrief
from state import request as request_state


@contextmanager
def request_context():
  req = MagicMock()
  req.state = type("State", (), {})()
  token_req = request_state.set(req)
  try:
    yield req
  finally:
    request_state.reset(token_req)
    for attr in list(vars(req.state).keys()):
      delattr(req.state, attr)


class TestDebugMetricsHelper:
  def test_state_key_uses_module_suffix(self):
    assert debug_metrics.state_key("caveman") == "caveman_debug"

  def test_record_and_get_round_trip(self):
    with request_context() as req:
      debug_metrics.record(
        "caveman",
        debug_metrics.triggered_payload(
          "triggered",
          duration_ms=12,
          extra_calls=2,
          queries=3,
        ),
      )

      stored = debug_metrics.get("caveman")
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.duration_ms == 12
      assert stored.extra_calls == 2
      assert stored.extra["queries"] == 3
      assert getattr(req.state, "caveman_debug") == stored.model_dump()

  def test_record_returns_none_without_request_context(self):
    assert debug_metrics.record("caveman", debug_metrics.skipped_payload("acknowledgment")) is None
    assert debug_metrics.get("caveman") is None

  def test_skipped_payload_defaults(self):
    payload = debug_metrics.skipped_payload("acknowledgment", duration_ms=5)
    assert payload.triggered is False
    assert payload.skipped is True
    assert payload.reason == "acknowledgment"
    assert payload.duration_ms == 5
    assert payload.extra_calls == 0


class TestAutocheckDebugMetrics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_records_skip_metrics_on_request_state(self):
    chat = self._chat("ok")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()

    with request_context():
      with patch(
        "modules.autocheck.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await autocheck.apply(chat, llm)

      stored = debug_metrics.get(autocheck.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "acknowledgment"
      assert stored.extra_calls == 0
      assert stored.extra["verdict"] == "skipped"

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_with_extra_calls(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(return_value="Draft implementation")

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with request_context():
      with (
        patch.object(autocheck, "gather_workspace_context", new=AsyncMock(return_value="")),
        patch.object(autocheck, "run_audit", new=AsyncMock(return_value=(audit, debug))),
        patch.object(autocheck, "revise_draft", new=AsyncMock()) as revise,
      ):
        await autocheck.apply(chat, llm)

      revise.assert_not_called()
      stored = debug_metrics.get(autocheck.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.extra_calls == 2
      assert stored.extra["verdict"] == "pass"
      assert stored.duration_ms >= 0


class TestCavemanDebugMetrics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_records_skip_metrics_on_request_state(self):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with request_context():
      with patch(
        "modules.caveman.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await caveman.apply(chat, llm)

      stored = debug_metrics.get(caveman.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "acknowledgment"
      assert stored.extra_calls == 0

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_with_query_extraction_call(self):
    chat = self._chat("What is the Stripe checkout session API response format in 2024?")
    llm = MagicMock(module=caveman.ID_PREFIX)
    llm.emit_status = AsyncMock()

    brief = ResearchBrief(
      query=chat.match_one(role="user", index=-1).content,
      searches=[{
        "title": "Stripe Checkout API",
        "url": "https://docs.stripe.com/checkout",
        "snippet": "Checkout session response fields",
      }],
    )

    with request_context():
      with (
        patch.object(caveman, "extract_search_queries", new=AsyncMock(return_value=["stripe checkout api"])),
        patch.object(caveman, "gather_research", new=AsyncMock(return_value=brief)),
        patch(
          "modules.caveman.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ),
      ):
        await caveman.apply(chat, llm)

      stored = debug_metrics.get(caveman.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.extra_calls == 1
      assert stored.extra["queries"] == 1

  @pytest.mark.asyncio
  async def test_apply_records_llm_classifier_extra_call_on_skip(self):
    original_trigger = config.CAVEMAN_TRIGGER.__value__
    config.CAVEMAN_TRIGGER.__value__ = "llm"
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    llm.emit_status = AsyncMock()

    try:
      with request_context():
        with (
          patch.object(
            caveman,
            "classify_needs_research",
            new=AsyncMock(return_value=False),
          ),
          patch(
            "modules.caveman.workflow_mod.complete_or_defer",
            new=AsyncMock(return_value="ok"),
          ),
        ):
          await caveman.apply(chat, llm)

        stored = debug_metrics.get(caveman.ID_PREFIX)
        assert stored is not None
        assert stored.triggered is False
        assert stored.skipped is True
        assert stored.reason == "llm_classifier_no"
        assert stored.extra_calls == 1
    finally:
      config.CAVEMAN_TRIGGER.__value__ = original_trigger