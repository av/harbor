"""Unit tests for the keel Boost module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import keel


class TestKeelHeuristics:
  def _chat(self, *messages: str) -> ch.Chat:
    conversation = [{"role": "user", "content": msg} for msg in messages]
    return ch.Chat.from_conversation(conversation)

  def test_is_substantive_rejects_acknowledgments(self):
    assert not keel.is_substantive_message("thanks!")
    assert not keel.is_substantive_message("ok")

  def test_is_substantive_accepts_coding_request(self):
    assert keel.is_substantive_message("Implement retry helper in services/boost/src/utils.py")

  def test_is_done_signal_detects_completion_phrases(self):
    assert keel.is_done_signal("We're done, ship it.")
    assert not keel.is_done_signal("Implement the helper next.")

  def test_count_user_turns(self):
    chat = self._chat("first", "second", "third")
    assert keel.count_user_turns(chat) == 3

  def test_detect_drift_on_scope_expansion_phrase(self):
    assert keel.detect_drift("While you're at it, also add logging.")

  def test_detect_drift_on_out_of_scope_path(self):
    brief = keel.TaskBrief(
      objective="Fix utils",
      in_scope_paths=["services/boost/src/utils.py"],
    )
    assert keel.detect_drift("Please update docs/CHANGELOG.md too.", brief)

  def test_needs_keel_for_coding_deliverable(self):
    chat = self._chat("Implement helper in services/boost/src/utils.py")
    assert keel.needs_keel(chat)

  def test_needs_keel_skips_when_disabled(self):
    chat = self._chat("Implement helper in services/boost/src/utils.py")
    original = config.KEEL_ENABLED.__value__
    try:
      config.KEEL_ENABLED.__value__ = False
      assert not keel.needs_keel(chat)
    finally:
      config.KEEL_ENABLED.__value__ = original


class TestKeelBriefRendering:
  def test_render_anchor_block_includes_next_criterion(self):
    brief = keel.TaskBrief(
      objective="Add retry helper",
      constraints=["Keep changes minimal"],
      acceptance_criteria=["Helper retries 3 times", "Tests pass"],
      in_scope_paths=["services/boost/src/utils.py"],
    )
    rendered = keel.render_anchor_block(brief, "Helper retries 3 times")
    assert "<task_anchor>" in rendered
    assert "<objective>Add retry helper</objective>" in rendered
    assert "Keep changes minimal" in rendered
    assert "<next_criterion>" in rendered
    assert "Helper retries 3 times" in rendered
    assert "services/boost/src/utils.py" in rendered

  def test_next_unmet_criterion_skips_met_items(self):
    brief = keel.TaskBrief(
      objective="Ship feature",
      acceptance_criteria=["Add API route", "Add tests"],
    )
    assert keel.next_unmet_criterion(brief, {0}) == "Add tests"
    assert keel.next_unmet_criterion(brief, {0, 1}) is None

  def test_render_landing_checklist_marks_met_criteria(self):
    brief = keel.TaskBrief(
      objective="Ship feature",
      acceptance_criteria=["Add API route", "Add tests"],
      in_scope_paths=["src/api.py"],
    )
    with patch.object(keel, "get_met_criteria", return_value={0}):
      rendered = keel.render_landing_checklist(brief, drift_detected=True)

    assert "<landing_checklist>" in rendered
    assert "[x] Add API route" in rendered
    assert "[ ] Add tests" in rendered
    assert "<drift_warning>" in rendered


class TestKeelExtraction:
  @pytest.mark.asyncio
  async def test_extract_task_brief_parses_structured_result(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.url = "http://example.com"
    llm.headers = {}
    llm.query_params = {}
    llm.model = "test-model"

    with patch.object(keel, "_cheap_llm") as cheap_llm:
      cheap = MagicMock()
      cheap.chat_completion = AsyncMock(
        return_value={
          "objective": "Add retry helper",
          "constraints": ["No new dependencies"],
          "acceptance_criteria": ["Retries transient errors"],
          "in_scope_paths": ["services/boost/src/utils.py"],
        }
      )
      cheap_llm.return_value = cheap

      brief = await keel.extract_task_brief(chat, llm, "Implement retry helper")

    assert brief.objective == "Add retry helper"
    assert brief.constraints == ["No new dependencies"]
    assert brief.acceptance_criteria == ["Retries transient errors"]


class TestKeelApply:
  @pytest.mark.asyncio
  async def test_apply_passes_through_non_deliverable(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Explain Python dataclasses briefly."},
    ])
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with patch.object(keel, "ensure_task_brief", new=AsyncMock()) as ensure:
      await keel.apply(chat, llm)

    ensure.assert_not_called()
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_extracts_brief_on_first_substantive_turn(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = keel.TaskBrief(
      objective="Add retry helper",
      acceptance_criteria=["Helper retries 3 times"],
      in_scope_paths=["services/boost/src/utils.py"],
    )

    with (
      patch.object(keel, "get_stored_brief", return_value=None),
      patch.object(keel, "ensure_task_brief", new=AsyncMock(return_value=brief)) as ensure,
      patch.object(keel, "_register_finish_wrapper") as register_finish,
    ):
      await keel.apply(chat, llm)

    ensure.assert_awaited_once()
    register_finish.assert_called_once_with(brief, False)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_anchor_on_second_turn(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Added retry helper with three attempts."},
      {"role": "user", "content": "Add tests for the retry helper."},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = keel.TaskBrief(
      objective="Add retry helper",
      constraints=["Keep changes minimal"],
      acceptance_criteria=["Helper retries 3 times", "Tests pass"],
      in_scope_paths=["services/boost/src/utils.py"],
    )

    with (
      patch.object(keel, "get_stored_brief", return_value=brief),
      patch.object(keel, "update_met_criteria_from_history", return_value=set()),
      patch.object(keel, "_register_finish_wrapper"),
    ):
      await keel.apply(chat, llm)

    history = chat.history()
    assert any("<task_anchor>" in (msg.get("content") or "") for msg in history)
    llm.stream_final_completion.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_apply_injects_landing_checklist_on_done_signal(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
      {"role": "assistant", "content": "Done implementing."},
      {"role": "user", "content": "Looks good, we're done."},
    ])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    llm.stream_final_completion = AsyncMock()

    brief = keel.TaskBrief(
      objective="Add retry helper",
      acceptance_criteria=["Helper retries 3 times"],
    )

    with (
      patch.object(keel, "get_stored_brief", return_value=brief),
      patch.object(keel, "update_met_criteria_from_history", return_value=set()),
      patch.object(keel, "_register_finish_wrapper"),
    ):
      await keel.apply(chat, llm)

    history = chat.history()
    assert any("<landing_checklist>" in (msg.get("content") or "") for msg in history)

  @pytest.mark.asyncio
  async def test_finish_wrapper_prepends_checklist(self):
    brief = keel.TaskBrief(
      objective="Add retry helper",
      acceptance_criteria=["Helper retries 3 times"],
    )

    with patch("modules.keel.tools.registry.set_local_tool") as set_tool:
      keel._register_finish_wrapper(brief, drift_detected=False)

    finish_tool = set_tool.call_args.args[1]
    result = await finish_tool("Final answer body.")
    assert "<landing_checklist>" in result
    assert "Final answer body." in result