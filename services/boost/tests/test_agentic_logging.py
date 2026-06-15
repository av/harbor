"""Tests for consistent gate/skip logging across agentic Boost modules."""

import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import autocheck, caveman, diffscope, keel, ponytail, sightline
from research import orchestrate


@pytest.fixture(autouse=True)
def _enable_module_log_propagation():
  """Enable propagation on agentic module loggers so caplog can capture them."""
  logger_names = [
    "caveman",
    "ponytail",
    "autocheck",
    "keel",
    "sightline",
    "diffscope",
    "research.orchestrate",
  ]
  originals = {}
  for name in logger_names:
    lg = logging.getLogger(name)
    originals[name] = lg.propagate
    lg.propagate = True
  yield
  for name, val in originals.items():
    logging.getLogger(name).propagate = val


class TestLowValueSkipReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_acknowledgment(self):
    assert orchestrate.low_value_skip_reason(self._chat("thanks!")) == "acknowledgment"

  def test_continuation(self):
    assert orchestrate.low_value_skip_reason(self._chat("carry on as planned")) == "continuation"

  def test_empty_or_short(self):
    assert orchestrate.low_value_skip_reason(self._chat("ok")) == "empty_or_short_message"


class TestCavemanGateReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skip_reason_for_acknowledgment(self):
    assert caveman.research_skip_reason(self._chat("thanks")) == "acknowledgment"

  def test_skip_reason_for_coding_without_research_signals(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert caveman.research_skip_reason(chat) == "coding_no_research_signals"

  @pytest.mark.asyncio
  async def test_gate_reason_heuristic_no_match(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    assert await caveman.research_gate_reason(chat, llm) == "heuristic_no_match"

  @pytest.mark.asyncio
  async def test_gate_reason_triggered_with_module_prefix(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=caveman.ID_PREFIX)
    assert await caveman.research_gate_reason(chat, llm) == "triggered"

  @pytest.mark.asyncio
  async def test_apply_logs_pass_through_reason(self, caplog):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="caveman"):
      with patch(
        "modules.caveman.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await caveman.apply(chat, llm)

    assert any(
      "Pass-through — acknowledgment" in record.message
      for record in caplog.records
    )


class TestPonytailGateReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skip_reason_for_acknowledgment(self):
    assert ponytail.research_skip_reason(self._chat("thanks!")) == "acknowledgment"

  @pytest.mark.asyncio
  async def test_gate_reason_not_research_heavy(self):
    chat = self._chat("What is asyncio.gather used for in Python?")
    llm = MagicMock(module=None)
    assert await ponytail.research_gate_reason(chat, llm) == "not_research_heavy"


class TestKeelGateReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_disabled(self):
    chat = self._chat("Implement helper in utils.py")
    original = config.KEEL_ENABLED.__value__
    try:
      config.KEEL_ENABLED.__value__ = False
      assert keel.keel_gate_reason(chat) == "disabled"
    finally:
      config.KEEL_ENABLED.__value__ = original

  def test_not_coding_deliverable(self):
    chat = self._chat("Explain what asyncio.gather does.")
    assert keel.keel_gate_reason(chat) == "not_coding_deliverable"

  @pytest.mark.asyncio
  async def test_apply_logs_pass_through_reason(self, caplog):
    chat = self._chat("Explain what asyncio.gather does.")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="keel"):
      with patch(
        "modules.keel.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await keel.apply(chat, llm)

    assert any(
      "Pass-through — not_coding_deliverable" in record.message
      for record in caplog.records
    )


class TestDiffscopeGateReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_not_deliverable(self):
    chat = self._chat("Explain what asyncio.gather does.")
    assert diffscope.diffscope_gate_reason(chat) == "not_deliverable"

  def test_no_scope_constraints(self):
    chat = self._chat("Implement a retry helper with exponential backoff.")
    assert diffscope.diffscope_gate_reason(chat) == "no_scope_constraints"

  def test_triggered_with_scope(self):
    chat = self._chat("Only change services/boost/src/utils.py for the retry helper.")
    assert diffscope.diffscope_gate_reason(chat) == "triggered"


class TestAutocheckGateLogging:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  @pytest.mark.asyncio
  async def test_apply_logs_gate_reason_on_skip(self, caplog):
    chat = self._chat("ok")
    llm = MagicMock()
    llm.boost_params = {}
    llm.emit_status = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="autocheck"):
      with patch(
        "modules.autocheck.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await autocheck.apply(chat, llm)

    assert any(
      "Pass-through — acknowledgment" in record.message
      for record in caplog.records
    )


class TestSightlineGateLogging:
  @pytest.mark.asyncio
  async def test_apply_logs_when_no_tools_registered(self, caplog):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "hello"}])
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="sightline"):
      with patch("modules.sightline.install_guards", return_value=[]):
        with patch(
          "modules.sightline.workflow_mod.complete_or_defer",
          new=AsyncMock(return_value="ok"),
        ):
          await sightline.apply(chat, llm)

    assert any(
      "Pass-through — no_file_tools_registered" in record.message
      for record in caplog.records
    )

  def test_workspace_guard_skip_reason_when_disabled(self, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_ROOT", MagicMock(value="/workspace"))
    monkeypatch.setattr(config, "SIGHTLINE_WORKSPACE", MagicMock(value=False))
    assert sightline.workspace_guard_skip_reason() == "workspace_guard_disabled"