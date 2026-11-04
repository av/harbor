"""Tests for selection.matches_filter (HARBOR_BOOST_MODEL_FILTER matching)."""

import selection
from config import ConfigDict


MODEL = {"id": "llama3.1:8b", "owned_by": "ollama"}


class TestMatchesFilter:
    def test_all_keys_must_match(self):
        f = ConfigDict.from_string("id.contains=llama,owned_by=openai")
        assert selection.matches_filter(MODEL, f) is False

    def test_later_key_checked_after_exact_match(self):
        f = ConfigDict.from_string("owned_by=ollama,id.regex=^qwen")
        assert selection.matches_filter(MODEL, f) is False

    def test_all_keys_matching(self):
        f = ConfigDict.from_string("id.contains=llama,owned_by=ollama")
        assert selection.matches_filter(MODEL, f) is True
