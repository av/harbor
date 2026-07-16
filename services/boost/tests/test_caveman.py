"""Unit tests for the caveman terse-style Boost module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import caveman
from modules import style as style_mod


class TestCavemanResolveStyleLevel:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_uses_config_default_when_no_override(self):
    original = config.CAVEMAN_LEVEL.__value__
    try:
      config.CAVEMAN_LEVEL.__value__ = "ultra"
      level = style_mod.resolve_style_level(
        self._chat("Implement retry helper in utils.py"),
        default=config.CAVEMAN_LEVEL.value,
      )
      assert level == "ultra"
    finally:
      config.CAVEMAN_LEVEL.__value__ = original

  def test_command_overrides_config_default(self):
    original = config.CAVEMAN_LEVEL.__value__
    try:
      config.CAVEMAN_LEVEL.__value__ = "full"
      level = style_mod.resolve_style_level(
        self._chat("Please /caveman lite summarize the migration plan."),
        default=config.CAVEMAN_LEVEL.value,
      )
      assert level == "lite"
    finally:
      config.CAVEMAN_LEVEL.__value__ = original

  def test_stop_caveman_disables_style(self):
    level = style_mod.resolve_style_level(
      self._chat("stop caveman and answer normally."),
      default=config.CAVEMAN_LEVEL.value,
    )
    assert level == "off"

  def test_normal_mode_disables_style(self):
    level = style_mod.resolve_style_level(
      self._chat("switch to normal mode for this answer."),
      default=config.CAVEMAN_LEVEL.value,
    )
    assert level == "off"

  def test_ponytail_command_does_not_affect_caveman(self):
    level = style_mod.resolve_style_level(
      self._chat("/ponytail ultra please"),
      default="full",
      module="caveman",
    )
    assert level == "full"

  def test_stop_ponytail_does_not_disable_caveman(self):
    level = style_mod.resolve_style_level(
      self._chat("stop ponytail now"),
      default="full",
      module="caveman",
    )
    assert level == "full"

  def test_workflow_config_level_overrides_default(self):
    level = style_mod.resolve_style_level(
      self._chat("Implement retry helper in utils.py"),
      default=config.CAVEMAN_LEVEL.value,
      config_level="wenyan-full",
    )
    assert level == "wenyan-full"


class TestCavemanApply:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_injects_caveman_style_block_and_completes(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await caveman.apply(chat, llm)

    history = chat.history()
    style_messages = [
      msg.get("content") or ""
      for msg in history
      if "<caveman_style" in (msg.get("content") or "")
    ]
    assert len(style_messages) == 1
    assert 'active="true"' in style_messages[0]
    assert 'level="full"' in style_messages[0]
    assert caveman.CAVEMAN_PROMPT.splitlines()[0] in style_messages[0]
    assert "Intensity full:" in style_messages[0]
    complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_uses_command_level_in_injected_block(self):
    chat = self._chat("Please /caveman lite explain the retry helper.")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ):
      await caveman.apply(chat, llm)

    history = chat.history()
    style_messages = [
      msg.get("content") or ""
      for msg in history
      if "<caveman_style" in (msg.get("content") or "")
    ]
    assert len(style_messages) == 1
    assert 'level="lite"' in style_messages[0]
    assert "Intensity lite:" in style_messages[0]

  @pytest.mark.asyncio
  async def test_apply_merges_style_into_existing_system_message(self):
    chat = ch.Chat.from_conversation([
      {"role": "system", "content": "Existing harness instructions."},
      {"role": "user", "content": "Explain the retry helper."},
    ])
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ):
      await caveman.apply(chat, llm)

    history = chat.history()
    system_messages = [msg for msg in history if msg["role"] == "system"]
    assert len(system_messages) == 1
    assert "<caveman_style" in system_messages[0]["content"]
    assert "Existing harness instructions." in system_messages[0]["content"]

  @pytest.mark.asyncio
  async def test_apply_passes_through_without_injection_when_level_off(self):
    chat = self._chat("stop caveman and answer normally.")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await caveman.apply(chat, llm)

    history = chat.history()
    assert not any("<caveman_style" in (msg.get("content") or "") for msg in history)
    complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_workflow_config_sets_off(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await caveman.apply(chat, llm, config={"level": "off"})

    history = chat.history()
    assert not any("<caveman_style" in (msg.get("content") or "") for msg in history)
    complete_or_defer.assert_awaited_once_with(llm, {"level": "off"})
