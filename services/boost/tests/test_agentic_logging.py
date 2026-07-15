"""Tests for consistent gate/skip logging across agentic Boost modules."""

import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import config
from modules import autocheck, caveman, diffscope, ponytail, quickhop
from research import orchestrate


@pytest.fixture(autouse=True)
def _enable_module_log_propagation():
  """Enable propagation on agentic module loggers so caplog can capture them."""
  logger_names = [
    "quickhop",
    "deephop",
    "caveman",
    "ponytail",
    "autocheck",
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


class TestQuickhopGateReason:
  def _chat(self, content: str) -> ch.Chat:
    return ch.Chat.from_conversation([{"role": "user", "content": content}])

  def test_skip_reason_for_acknowledgment(self):
    assert quickhop.research_skip_reason(self._chat("thanks")) == "acknowledgment"

  def test_skip_reason_for_coding_without_research_signals(self):
    chat = self._chat("Implement retry helper in services/boost/src/utils.py")
    assert quickhop.research_skip_reason(chat) == "implementation_turn"

  @pytest.mark.asyncio
  async def test_gate_reason_heuristic_no_match(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=None)
    assert await quickhop.research_gate_reason(chat, llm) == ("heuristic_no_match", 0)

  @pytest.mark.asyncio
  async def test_gate_reason_triggered_with_module_prefix(self):
    chat = self._chat("Summarize how Harbor Boost modules are loaded.")
    llm = MagicMock(module=quickhop.ID_PREFIX)
    assert await quickhop.research_gate_reason(chat, llm) == ("triggered", 0)

  @pytest.mark.asyncio
  async def test_apply_logs_pass_through_reason(self, caplog):
    chat = self._chat("thanks")
    llm = MagicMock()
    llm.emit_status = AsyncMock()
    with caplog.at_level(logging.DEBUG, logger="quickhop"):
      with patch(
        "modules.quickhop.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await quickhop.apply(chat, llm)

    assert any(
      "Pass-through — acknowledgment" in record.message
      for record in caplog.records
    )
class TestCavemanStyleLogging:
  @pytest.mark.asyncio
  async def test_apply_logs_style_level(self, caplog):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    with caplog.at_level(logging.DEBUG, logger="caveman"):
      with patch(
        "modules.style.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await caveman.apply(chat, llm)

    assert any("level=full" in record.message for record in caplog.records)


class TestPonytailStyleLogging:
  @pytest.mark.asyncio
  async def test_apply_logs_style_level(self, caplog):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Implement retry helper in services/boost/src/utils.py"},
    ])
    llm = MagicMock()
    with caplog.at_level(logging.DEBUG, logger="ponytail"):
      with patch(
        "modules.style.workflow_mod.complete_or_defer",
        new=AsyncMock(return_value="ok"),
      ):
        await ponytail.apply(chat, llm)

    assert any("level=full" in record.message for record in caplog.records)


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
