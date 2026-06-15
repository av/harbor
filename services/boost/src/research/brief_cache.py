"""Request-scoped research brief cache for caveman and ponytail."""

import hashlib

import research.brief as brief_mod
from state import request_set, request_store


def question_hash(text: str) -> str:
  return hashlib.sha256((text or "").strip().encode()).hexdigest()


def get_cached_brief(
  cache_key: str,
  message: str,
  *,
  enabled: bool,
) -> brief_mod.ResearchBrief | None:
  if not enabled:
    return None

  cached = request_store(cache_key, None)
  if not isinstance(cached, tuple) or len(cached) != 2:
    return None

  cached_hash, cached_brief = cached
  if cached_hash != question_hash(message):
    return None
  if not isinstance(cached_brief, brief_mod.ResearchBrief):
    return None

  return cached_brief.model_copy(deep=True)


def store_cached_brief(
  cache_key: str,
  message: str,
  brief: brief_mod.ResearchBrief,
  *,
  enabled: bool,
) -> None:
  if not enabled:
    return

  request_set(
    cache_key,
    (question_hash(message), brief.model_copy(deep=True)),
  )