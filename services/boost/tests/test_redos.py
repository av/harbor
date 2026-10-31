"""Regression tests for super-linear regex matching on user or web input."""

import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chat as ch
import research.fetch as fetch
from custom_modules import discussurl
from modules import autocheck

FAST_SECONDS = 0.1


def timed(fn, *args):
  start = time.perf_counter()
  result = fn(*args)
  return result, time.perf_counter() - start


class TestDiscussUrlRedos:
  @pytest.mark.parametrize("n", [28, 10_000])
  def test_attack_input_is_fast(self, n):
    urls, elapsed = timed(discussurl.extract_urls, "https://" + "!" * n)
    assert urls == []
    assert elapsed < FAST_SECONDS

  @pytest.mark.parametrize("text", [
    "https://a(" * 9_000,
    "https://a)" * 9_000,
    "a." * 45_000 + "/",
    "-.-" * 30_000 + "/",
    "www." * 20_000,
    "(" * 200_000,
    "https://" + "x" * 1_000_000,
  ])
  def test_adversarial_shapes_are_fast(self, text):
    _, elapsed = timed(discussurl.extract_urls, text)
    assert elapsed < FAST_SECONDS


class TestDiscussUrlExtraction:
  @pytest.mark.parametrize("text, expected", [
    ("Summarize https://example.com/page.", ["https://example.com/page"]),
    ("http://x.org/a?b=c&d=e!", ["http://x.org/a?b=c&d=e"]),
    (
      "See (https://en.wikipedia.org/wiki/Python_(programming_language)).",
      ["https://en.wikipedia.org/wiki/Python_(programming_language)"],
    ),
    (
      "https://en.wikipedia.org/wiki/Foo_(bar_(baz)), ok",
      ["https://en.wikipedia.org/wiki/Foo_(bar_(baz))"],
    ),
    ("visit www.example.com/docs; then github.com/av/harbor.", ["www.example.com/docs", "github.com/av/harbor"]),
    ("<https://a.com/x> and \"https://b.com/y\"", ["https://a.com/x", "https://b.com/y"]),
    ("markdown [link](https://a.com/p) text", ["https://a.com/p"]),
    ("Repo:github.com/av/harbor and www.example.com/.", ["github.com/av/harbor", "www.example.com/"]),
    ("unclosed https://a.com/x(y", ["https://a.com/x"]),
    ("HTTPS://EXAMPLE.COM/UP", ["HTTPS://EXAMPLE.COM/UP"]),
    ("no links, just a@b.com", []),
  ])
  def test_extracts_urls(self, text, expected):
    assert discussurl.extract_urls(text) == expected

  def test_url_count_is_capped(self):
    text = " ".join(f"https://example.com/{i}" for i in range(50))
    assert len(discussurl.extract_urls(text)) == discussurl.MAX_URLS

  def test_overlong_url_is_skipped(self):
    text = "https://example.com/" + "a" * discussurl.MAX_URL_CHARS + " https://example.com/ok"
    assert discussurl.extract_urls(text) == ["https://example.com/ok"]

  def test_only_tail_of_long_text_is_scanned(self):
    text = "https://old.example.com/x " + "word " * discussurl.MAX_TEXT_CHARS + "https://new.example.com/y"
    assert discussurl.extract_urls(text) == ["https://new.example.com/y"]

  @pytest.mark.asyncio
  async def test_apply_reads_each_url(self):
    chat = ch.Chat.from_conversation([
      {"role": "user", "content": "Compare https://a.com/x and https://en.wikipedia.org/wiki/Foo_(bar)."},
    ])
    llm = SimpleNamespace(emit_status=AsyncMock(), stream_final_completion=AsyncMock())
    with patch.object(discussurl.requests, "get", return_value=SimpleNamespace(text="page")) as get:
      await discussurl.apply(chat, llm)
    assert [c.args[0] for c in get.call_args_list] == [
      "https://r.jina.ai/https://a.com/x",
      "https://r.jina.ai/https://en.wikipedia.org/wiki/Foo_(bar)",
    ]
    assert llm.stream_final_completion.await_args.kwargs["content"] == "pagepage"

  @pytest.mark.asyncio
  async def test_apply_attack_input_skips_reading(self):
    chat = ch.Chat.from_conversation([{"role": "user", "content": "https://" + "!" * 10_000}])
    llm = SimpleNamespace(emit_status=AsyncMock(), stream_final_completion=AsyncMock())
    with patch.object(discussurl.requests, "get") as get:
      start = time.perf_counter()
      await discussurl.apply(chat, llm)
      elapsed = time.perf_counter() - start
    get.assert_not_called()
    llm.stream_final_completion.assert_awaited_once_with()
    assert elapsed < FAST_SECONDS


class TestAutocheckSymbolsRedos:
  def test_blank_lines_are_fast(self):
    _, elapsed = timed(autocheck.extract_audit_symbols, "\n" * 100_000)
    assert elapsed < FAST_SECONDS

  def test_symbols_still_found(self):
    text = "def top():\n  pass\n\n    async def nested_call():\n\tclass Widget:\n"
    assert autocheck.extract_audit_symbols(text) == ["top", "nested_call", "Widget"]


class TestStripHtmlRedos:
  @pytest.mark.parametrize("raw", [
    "<style" * 50_000,
    '<file path="a' * 50_000,
    "<" * 300_000,
  ])
  def test_unclosed_tags_are_fast(self, raw):
    _, elapsed = timed(fetch._strip_html, raw)
    assert elapsed < FAST_SECONDS

  def test_strips_blocks_and_tags(self):
    raw = (
      "<html><head><STYLE>p{}</style><script src=x></Script></head>"
      "<body><p>Hello &amp; welcome</p><noscript>no js</noscript>"
      "<div title='x'>bye</div></body></html>"
    )
    assert fetch._strip_html(raw) == "Hello & welcome bye"

  def test_unclosed_script_is_not_dropped(self):
    assert fetch._strip_html("<p>a</p><script>b") == "a b"
