"""Unit tests for the ponytail YAGNI-style Boost module."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import ponytail
from modules import style as style_mod


class TestPonytailResolveStyleLevel:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_uses_config_default_when_no_override(self):
    original = config.PONYTAIL_LEVEL.__value__
    try:
      config.PONYTAIL_LEVEL.__value__ = "ultra"
      level = style_mod.resolve_style_level(
        self._chat("Implement retry helper in utils.py"),
        default=config.PONYTAIL_LEVEL.value,
      )
      assert level == "ultra"
    finally:
      config.PONYTAIL_LEVEL.__value__ = original

  def test_command_overrides_config_default(self):
    original = config.PONYTAIL_LEVEL.__value__
    try:
      config.PONYTAIL_LEVEL.__value__ = "full"
      level = style_mod.resolve_style_level(
        self._chat("Please /ponytail ultra add the retry helper."),
        default=config.PONYTAIL_LEVEL.value,
      )
      assert level == "ultra"
    finally:
      config.PONYTAIL_LEVEL.__value__ = original

  def test_stop_ponytail_disables_style(self):
    level = style_mod.resolve_style_level(
      self._chat("stop ponytail and build the full version."),
      default=config.PONYTAIL_LEVEL.value,
    )
    assert level == "off"

  def test_normal_mode_disables_style(self):
    level = style_mod.resolve_style_level(
      self._chat("switch to normal mode for this answer."),
      default=config.PONYTAIL_LEVEL.value,
    )
    assert level == "off"

  def test_caveman_command_does_not_affect_ponytail(self):
    level = style_mod.resolve_style_level(
      self._chat("/caveman lite please"),
      default="full",
      module="ponytail",
    )
    assert level == "full"

  def test_stop_caveman_does_not_disable_ponytail(self):
    level = style_mod.resolve_style_level(
      self._chat("stop caveman now"),
      default="full",
      module="ponytail",
    )
    assert level == "full"

  def test_workflow_config_level_overrides_default(self):
    level = style_mod.resolve_style_level(
      self._chat("Implement retry helper in utils.py"),
      default=config.PONYTAIL_LEVEL.value,
      config_level="lite",
    )
    assert level == "lite"


class TestPonytailApply:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_injects_ponytail_style_block_and_completes(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()
    llm.stream_final_completion = AsyncMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await ponytail.apply(chat, llm)

    history = chat.history()
    style_messages = [
      msg.get("content") or ""
      for msg in history
      if "<ponytail_style" in (msg.get("content") or "")
    ]
    assert len(style_messages) == 1
    assert 'active="true"' in style_messages[0]
    assert 'level="full"' in style_messages[0]
    assert ponytail.PONYTAIL_PROMPT.splitlines()[0] in style_messages[0]
    assert "Intensity full:" in style_messages[0]
    complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_uses_command_level_in_injected_block(self):
    chat = self._chat("Please /ponytail ultra add the retry helper.")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ):
      await ponytail.apply(chat, llm)

    history = chat.history()
    style_messages = [
      msg.get("content") or ""
      for msg in history
      if "<ponytail_style" in (msg.get("content") or "")
    ]
    assert len(style_messages) == 1
    assert 'level="ultra"' in style_messages[0]
    assert "Intensity ultra:" in style_messages[0]

  @pytest.mark.asyncio
  async def test_apply_passes_through_without_injection_when_level_off(self):
    chat = self._chat("stop ponytail and build the full version.")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await ponytail.apply(chat, llm)

    history = chat.history()
    assert not any("<ponytail_style" in (msg.get("content") or "") for msg in history)
    complete_or_defer.assert_awaited_once_with(llm, None)

  @pytest.mark.asyncio
  async def test_apply_passes_through_when_workflow_config_sets_off(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    llm = MagicMock()

    with patch(
      "modules.style.workflow_mod.complete_or_defer",
      new=AsyncMock(return_value="ok"),
    ) as complete_or_defer:
      await ponytail.apply(chat, llm, config={"level": "off"})

    history = chat.history()
    assert not any("<ponytail_style" in (msg.get("content") or "") for msg in history)
    complete_or_defer.assert_awaited_once_with(llm, {"level": "off"})