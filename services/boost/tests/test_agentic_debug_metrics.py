"""Tests for optional agentic module debug payloads on request.state."""

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import autocheck, deephop, diffscope, quickhop
from research import debug_metrics, workflow as workflow_mod
from research.brief import ResearchBrief
from state import request as request_state
from helpers import mock_autocheck_cheap_llm


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
  async def test_apply_records_draft_failure_skip_metrics(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()

    with request_context():
      with (
        patch.object(
          autocheck,
          "generate_draft",
          new=AsyncMock(side_effect=RuntimeError("draft down")),
        ),
        patch(
          "modules.autocheck.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ),
      ):
        await autocheck.apply(chat, llm)

      stored = debug_metrics.get(autocheck.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is True
      assert stored.reason == "draft_generation_failed"
      assert stored.extra["verdict"] == "skipped"

    status_messages = [call.args[0] for call in llm.emit_status.await_args_list]
    assert "Autocheck: skipped (draft_generation_failed)" in status_messages

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_with_extra_calls(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()

    audit = autocheck.AuditResult(verdict="pass", summary="Ship it")
    debug = autocheck.AuditDebug(triggered=True, gate_reason="triggered", verdict="pass")

    with request_context():
      with (
        patch(
          "research.orchestrate.cheap_llm",
          return_value=mock_autocheck_cheap_llm(),
        ),
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


class TestQuickhopDebugMetrics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_records_acknowledgment_pass_through_debug_metrics(self):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with request_context() as req:
      with patch(
        "modules.quickhop.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ) as complete_or_defer:
        await quickhop.apply(chat, llm)

      stored = debug_metrics.get(quickhop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "acknowledgment"
      assert stored.extra_calls == 0
      assert stored.duration_ms >= 0
      assert getattr(req.state, debug_metrics.state_key(quickhop.ID_PREFIX)) == stored.model_dump()

      llm.emit_status.assert_awaited_once_with(
        quickhop.format_skipped_status("acknowledgment"),
      )
      complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_with_query_extraction_call(self):
    chat = self._chat("What is the Stripe checkout session API response format in 2024?")
    llm = MagicMock(module=quickhop.ID_PREFIX)
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
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=["stripe checkout api"])),
        patch.object(quickhop, "gather_research", new=AsyncMock(return_value=brief)),
        patch(
          "modules.quickhop.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ),
      ):
        await quickhop.apply(chat, llm)

      stored = debug_metrics.get(quickhop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.extra_calls == 1
      assert stored.extra["queries"] == 1

  @pytest.mark.asyncio
  async def test_apply_records_llm_classifier_extra_call_on_skip(self):
    original_trigger = config.QUICKHOP_TRIGGER.__value__
    config.QUICKHOP_TRIGGER.__value__ = "llm"
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    llm.emit_status = AsyncMock()

    try:
      with request_context():
        with (
          patch.object(
            quickhop,
            "classify_needs_research",
            new=AsyncMock(return_value=False),
          ),
          patch(
            "modules.quickhop.workflow_mod.complete_or_defer",
            new=AsyncMock(return_value="ok"),
          ),
        ):
          await quickhop.apply(chat, llm)

        stored = debug_metrics.get(quickhop.ID_PREFIX)
        assert stored is not None
        assert stored.triggered is False
        assert stored.skipped is True
        assert stored.reason == "llm_classifier_no"
        assert stored.extra_calls == 1
    finally:
      config.QUICKHOP_TRIGGER.__value__ = original_trigger

  @pytest.mark.asyncio
  async def test_apply_llm_trigger_does_not_count_classifier_on_early_skip(self):
    original_trigger = config.QUICKHOP_TRIGGER.__value__
    config.QUICKHOP_TRIGGER.__value__ = "llm"
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    try:
      with request_context():
        with (
          patch.object(
            quickhop,
            "classify_needs_research",
            new=AsyncMock(return_value=True),
          ) as classify,
          patch(
            "modules.quickhop.workflow_mod.complete_or_defer",
            new=AsyncMock(return_value="ok"),
          ),
        ):
          await quickhop.apply(chat, llm)

        classify.assert_not_called()
        stored = debug_metrics.get(quickhop.ID_PREFIX)
        assert stored is not None
        assert stored.reason == "acknowledgment"
        assert stored.extra_calls == 0
    finally:
      config.QUICKHOP_TRIGGER.__value__ = original_trigger

  @pytest.mark.asyncio
  async def test_apply_records_skipped_metrics_when_no_queries_extracted(self):
    chat = self._chat("What is the Stripe checkout session API response format in 2024?")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    llm.emit_status = AsyncMock()

    with request_context():
      with (
        patch.object(quickhop, "extract_search_queries", new=AsyncMock(return_value=[])),
        patch(
          "modules.quickhop.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ) as complete_or_defer,
      ):
        await quickhop.apply(chat, llm)

      stored = debug_metrics.get(quickhop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "no_queries_extracted"
      assert stored.extra_calls == 1

      statuses = [call.args[0] for call in llm.emit_status.await_args_list]
      assert statuses[-1] == quickhop.format_skipped_status("no_queries_extracted")
      complete_or_defer.assert_awaited_once_with(llm, None)


class TestDeephopDebugMetrics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_records_skip_metrics_on_request_state(self):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with request_context():
      with patch(
        "modules.deephop.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await deephop.apply(chat, llm)

      stored = debug_metrics.get(deephop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "acknowledgment"
      assert stored.extra_calls == 0

  @pytest.mark.asyncio
  async def test_apply_records_skipped_metrics_when_no_queries_planned(self):
    chat = self._chat(
      "What are the breaking changes when migrating from FastAPI 0.100 to 0.115?"
    )
    llm = MagicMock(module=deephop.ID_PREFIX)
    llm.emit_status = AsyncMock()

    with request_context():
      with (
        patch.object(deephop, "plan_search_queries", new=AsyncMock(return_value=[])),
        patch(
          "modules.deephop.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ) as complete_or_defer,
      ):
        await deephop.apply(chat, llm)

      stored = debug_metrics.get(deephop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "no_queries_planned"
      assert stored.extra_calls == 1

      statuses = [call.args[0] for call in llm.emit_status.await_args_list]
      assert statuses[-1] == deephop.format_skipped_status("no_queries_planned")
      complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_with_research_calls(self):
    chat = self._chat(
      "What are the breaking changes when migrating from FastAPI 0.100 to 0.115?"
    )
    llm = MagicMock(module=deephop.ID_PREFIX)
    llm.emit_status = AsyncMock()

    brief = ResearchBrief(
      query=chat.match_one(role="user", index=-1).content,
      searches=[{
        "title": "FastAPI migration",
        "url": "https://fastapi.tiangolo.com/release-notes",
        "snippet": "Breaking changes in 0.115",
      }],
    )

    with request_context():
      with (
        patch.object(deephop, "plan_search_queries", new=AsyncMock(return_value=["fastapi 0.115 migration"])),
        patch.object(deephop, "run_research_loop", new=AsyncMock(return_value=(brief, 2))),
        patch(
          "modules.deephop.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ),
      ):
        await deephop.apply(chat, llm)

      stored = debug_metrics.get(deephop.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.extra_calls == 3
      assert stored.extra["queries"] == 1
      assert stored.extra["searches"] == 1


class TestDiffscopeDebugMetrics:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_records_skip_metrics_on_request_state(self):
    chat = self._chat("Implement a retry helper with exponential backoff for HTTP calls")
    llm = MagicMock()
    llm.emit_status = AsyncMock()

    with request_context():
      with patch(
        "modules.diffscope.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await diffscope.apply(chat, llm)

      stored = debug_metrics.get(diffscope.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is False
      assert stored.skipped is True
      assert stored.reason == "no_scope_constraints"
      assert stored.extra_calls == 0

  @pytest.mark.asyncio
  async def test_apply_records_trigger_metrics_on_scope_ok(self):
    chat = self._chat(
      "Fix the bug in services/boost/src/utils.py only — do not touch other files."
    )
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.emit_message = AsyncMock()
    llm.stream_chat_completion = AsyncMock(
      return_value="Updated services/boost/src/utils.py with the retry helper."
    )

    snapshot = diffscope.ChangedPathsSnapshot(
      paths=["services/boost/src/utils.py"],
      mode="heuristic",
    )

    with request_context():
      with (
        patch.object(diffscope, "collect_changed_paths", return_value=snapshot),
        patch.object(diffscope, "verify_workspace_paths", new=AsyncMock(return_value=[])),
      ):
        await diffscope.apply(chat, llm)

      stored = debug_metrics.get(diffscope.ID_PREFIX)
      assert stored is not None
      assert stored.triggered is True
      assert stored.skipped is False
      assert stored.reason == "triggered"
      assert stored.extra_calls == 1
      assert stored.extra["outcome"] == "scope_ok"
      assert stored.extra["grounding_mode"] == "heuristic"


class TestDebugSummaryHelpers:
  def test_debug_enabled_respects_boost_param(self):
    llm = MagicMock()
    original = config.BOOST_DEBUG.__value__
    try:
      config.BOOST_DEBUG.__value__ = False
      llm.boost_params = {"debug": "true"}
      assert debug_metrics.debug_enabled(llm)

      llm.boost_params = {"debug": "false"}
      assert not debug_metrics.debug_enabled(llm)
    finally:
      config.BOOST_DEBUG.__value__ = original

  def test_debug_enabled_falls_back_to_config(self):
    llm = MagicMock()
    llm.boost_params = {}
    original = config.BOOST_DEBUG.__value__
    try:
      config.BOOST_DEBUG.__value__ = True
      assert debug_metrics.debug_enabled(llm)

      config.BOOST_DEBUG.__value__ = False
      assert not debug_metrics.debug_enabled(llm)
    finally:
      config.BOOST_DEBUG.__value__ = original

  def test_collect_all_reads_debug_suffix_keys(self):
    with request_context() as req:
      debug_metrics.record(
        "caveman",
        debug_metrics.skipped_payload("acknowledgment", duration_ms=3),
      )
      debug_metrics.record(
        "quickhop",
        debug_metrics.triggered_payload(
          "triggered",
          duration_ms=12,
          extra_calls=1,
        ),
      )

      collected = debug_metrics.collect_all()
      assert set(collected) == {"caveman", "quickhop"}
      assert collected["caveman"]["reason"] == "acknowledgment"
      assert collected["quickhop"]["extra_calls"] == 1

  def test_format_compact_summary_renders_modules(self):
    summary = debug_metrics.format_compact_summary({
      "caveman": debug_metrics.skipped_payload("acknowledgment", duration_ms=3).model_dump(),
      "quickhop": debug_metrics.triggered_payload(
        "triggered",
        duration_ms=12,
        extra_calls=1,
      ).model_dump(),
    })
    assert summary.startswith("Debug:")
    assert "caveman skipped (acknowledgment) 3ms" in summary
    assert "quickhop triggered 12ms +1calls" in summary


class TestCompleteOrDeferDebugStatus:
  @pytest.mark.asyncio
  async def test_emits_compact_summary_when_debug_enabled(self):
    llm = MagicMock()
    llm.boost_params = {"debug": "true"}
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock(return_value="final")

    with request_context():
      debug_metrics.record(
        "caveman",
        debug_metrics.skipped_payload("acknowledgment", duration_ms=4),
      )
      result = await workflow_mod.complete_or_defer(llm)

    assert result == "final"
    llm.emit_status.assert_awaited_once()
    status = llm.emit_status.await_args.args[0]
    assert status.startswith("Debug:")
    assert "caveman skipped (acknowledgment) 4ms" in status
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_skips_summary_when_debug_disabled(self):
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock(return_value="final")

    original = config.BOOST_DEBUG.__value__
    try:
      config.BOOST_DEBUG.__value__ = False
      with request_context():
        debug_metrics.record(
          "caveman",
          debug_metrics.skipped_payload("acknowledgment", duration_ms=4),
        )
        await workflow_mod.complete_or_defer(llm)
    finally:
      config.BOOST_DEBUG.__value__ = original

    llm.emit_status.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_defer_final_skips_summary_and_stream(self):
    llm = MagicMock()
    llm.boost_params = {"debug": "true"}
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    with request_context():
      debug_metrics.record(
        "caveman",
        debug_metrics.skipped_payload("acknowledgment", duration_ms=4),
      )
      result = await workflow_mod.complete_or_defer(llm, {"defer_final": True})

    assert result is None
    llm.emit_status.assert_not_called()
    llm.stream_final_completion.assert_not_called()


class TestAnchorDeferredDraft:
  def test_replaces_assistant_tail_when_defer_final(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
      {"role": "assistant", "content": "Pre-revision draft touching src/bar.py"},
    ])
    scoped = "Only updated src/foo.py."

    workflow_mod.anchor_deferred_draft(chat, scoped, {"defer_final": True})

    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == [scoped]

  def test_appends_when_no_assistant_tail(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
    ])
    scoped = "Only updated src/foo.py."

    workflow_mod.anchor_deferred_draft(chat, scoped, {"defer_final": True})

    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == [scoped]

  def test_noop_without_defer_final(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
      {"role": "assistant", "content": "Pre-revision draft"},
    ])

    workflow_mod.anchor_deferred_draft(chat, "Revised answer", {"defer_final": False})

    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == ["Pre-revision draft"]

  def test_noop_on_empty_text(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
      {"role": "assistant", "content": "Pre-revision draft"},
    ])

    workflow_mod.anchor_deferred_draft(chat, "   ", {"defer_final": True})

    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == ["Pre-revision draft"]


class TestAnchorAndEmitFinal:
  @pytest.mark.asyncio
  async def test_emits_when_not_deferred(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
    ])
    llm = MagicMock()
    llm.emit_message = AsyncMock()

    result = await workflow_mod.anchor_and_emit_final(
      llm,
      chat,
      "Scoped fix.",
      {"defer_final": False},
    )

    assert result == "Scoped fix."
    llm.emit_message.assert_awaited_once_with("Scoped fix.")

  @pytest.mark.asyncio
  async def test_anchors_without_emit_when_deferred(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Only change src/foo.py"},
      {"role": "assistant", "content": "Pre-audit draft"},
    ])
    llm = MagicMock()
    llm.emit_message = AsyncMock()

    result = await workflow_mod.anchor_and_emit_final(
      llm,
      chat,
      "Scoped fix.",
      {"defer_final": True},
    )

    assert result == "Scoped fix."
    assistants = [
      msg.get("content") or ""
      for msg in chat.history()
      if msg.get("role") == "assistant"
    ]
    assert assistants == ["Scoped fix."]
    llm.emit_message.assert_not_called()