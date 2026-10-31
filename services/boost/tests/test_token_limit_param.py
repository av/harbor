"""Output token limit field for OpenAI reasoning models (#299)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anthropic_compat
from compat_utils import token_limit_param


@pytest.mark.parametrize("model", [
  "gpt-5", "gpt-5-mini", "GPT-5.1", "o1", "o3-mini", "o4-mini-2025-04-16",
  "openai/gpt-5-nano", "klmbr-gpt-5-mini", "rcn-o3",
])
def test_reasoning_models_use_max_completion_tokens(model):
  assert token_limit_param(model) == "max_completion_tokens"


@pytest.mark.parametrize("model", [
  "gpt-4o", "gpt-4.1-mini", "llama3.1:8b", "qwen3:4b", "gpt-50", "foo1",
  "docker.io/ai/smollm2:latest", "", None,
])
def test_other_models_keep_max_tokens(model):
  assert token_limit_param(model) == "max_tokens"


def test_anthropic_messages_for_gpt5():
  params = anthropic_compat._convert_params({"model": "gpt-5-mini", "max_tokens": 128})
  assert params == {"max_completion_tokens": 128}


def test_anthropic_messages_for_gpt5_thinking_disabled():
  params = anthropic_compat._convert_params(
    {"model": "o3", "max_tokens": 64, "thinking": {"type": "disabled"}}
  )
  assert params == {"max_completion_tokens": 64}


def test_anthropic_messages_for_local_model():
  params = anthropic_compat._convert_params({"model": "llama3.1:8b", "max_tokens": 128})
  assert params == {"max_tokens": 128}

