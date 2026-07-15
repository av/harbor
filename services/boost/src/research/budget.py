"""Research budget caps and enforcement helpers for agentic modules."""

from dataclasses import dataclass, field

import config

DEFAULT_MAX_SEARCHES = 3
DEFAULT_MAX_URL_READS = 2
DEFAULT_MAX_CHARS = 50_000


@dataclass
class ResearchBudget:
  max_searches: int = DEFAULT_MAX_SEARCHES
  max_url_reads: int = DEFAULT_MAX_URL_READS
  max_chars: int = DEFAULT_MAX_CHARS
  searches_used: int = field(default=0, init=False)
  url_reads_used: int = field(default=0, init=False)
  chars_used: int = field(default=0, init=False)

  def can_search(self) -> bool:
    return self.searches_used < self.max_searches

  def can_read_url(self) -> bool:
    return self.url_reads_used < self.max_url_reads

  def remaining_chars(self) -> int:
    return max(0, self.max_chars - self.chars_used)

  def record_search(self) -> None:
    if not self.can_search():
      raise BudgetExceeded("search", self.max_searches)
    self.searches_used += 1

  def record_url_read(self, chars: int = 0) -> None:
    if not self.can_read_url():
      raise BudgetExceeded("url_read", self.max_url_reads)
    self.url_reads_used += 1
    if chars:
      self.record_chars(chars)

  def record_chars(self, chars: int) -> None:
    if chars <= 0:
      return
    if self.chars_used + chars > self.max_chars:
      raise BudgetExceeded("chars", self.max_chars)
    self.chars_used += chars

  def trim_to_remaining(self, text: str) -> str:
    remaining = self.remaining_chars()
    if len(text) <= remaining:
      self.record_chars(len(text))
      return text
    trimmed = text[:remaining]
    self.record_chars(len(trimmed))
    return trimmed


class BudgetExceeded(Exception):
  def __init__(self, resource: str, limit: int):
    self.resource = resource
    self.limit = limit
    super().__init__(f"Research budget exceeded for {resource} (limit: {limit})")


def budget_from_config(module: str) -> ResearchBudget:
  """Build a module-specific research budget from Harbor Boost config."""
  module = module.lower()
  if module == "quickhop":
    return ResearchBudget(
      max_searches=config.QUICKHOP_MAX_SEARCHES.value,
      max_url_reads=config.QUICKHOP_MAX_URL_READS.value,
      max_chars=config.QUICKHOP_MAX_CHARS.value,
    )
  if module == "deephop":
    return ResearchBudget(
      max_searches=config.DEEPHOP_MAX_SEARCHES.value,
      max_url_reads=config.DEEPHOP_MAX_URL_READS.value,
      max_chars=config.DEEPHOP_MAX_CHARS.value,
    )
  return ResearchBudget()