"""Structured research briefs for agentic Boost modules."""

import re

from pydantic import BaseModel, Field

import research.fetch as fetch_mod

_VERSION_RE = re.compile(
  r"(?<![`.\w])"
  r"(v?\d+(?:\.\d+)+[a-z0-9]*|20\d{2}-\d{2}-\d{2})"
  r"(?![`.\w])",
  re.IGNORECASE,
)

RESEARCH_UNAVAILABLE_NOTE = (
  "Research unavailable: live web search and URL reading could not be completed. "
  "Answer from model knowledge and clearly state when facts could not be verified."
)


class ResearchSource(BaseModel):
  title: str = ""
  url: str = ""
  snippet: str = ""


class ResearchBrief(BaseModel):
  query: str = ""
  searches: list[ResearchSource] = Field(default_factory=list)
  pages: list[ResearchSource] = Field(default_factory=list)
  notes: list[str] = Field(default_factory=list)
  facts: list[str] = Field(default_factory=list)
  uncertainties: list[str] = Field(default_factory=list)
  recommendation: str = ""
  do_not_assume: list[str] = Field(default_factory=list)

  def add_search_results(self, query: str, results_text: str) -> None:
    if not self.query:
      self.query = query

    current: ResearchSource | None = None
    for line in results_text.splitlines():
      line = line.strip()
      if not line or line == "No results found.":
        continue

      if line[0].isdigit() and ". [" in line:
        title = "Untitled"
        url = ""
        snippet = ""

        _, rest = line.split(". ", 1)
        if "](" in rest and ")" in rest:
          title_part, remainder = rest.split("](", 1)
          title = title_part.lstrip("[")
          url, remainder = remainder.split(")", 1)
          remainder = remainder.strip()
          if remainder.startswith("(") and ")" in remainder:
            _, remainder = remainder.split(")", 1)
          snippet = remainder.strip()

        current = ResearchSource(title=title, url=url, snippet=snippet)
        self.searches.append(current)
        continue

      if current is not None:
        current.snippet = "\n".join(part for part in [current.snippet, line] if part)
      else:
        self.searches.append(ResearchSource(snippet=line))

  def add_page(self, url: str, content: str, *, title: str = "") -> None:
    self.pages.append(ResearchSource(title=title or url, url=url, snippet=content))

  def add_note(self, note: str) -> None:
    if note.strip():
      self.notes.append(note.strip())


def has_usable_research(brief: ResearchBrief) -> bool:
  """Return True when the brief contains at least one non-failure search hit or page."""
  for page in brief.pages:
    if page.snippet and not fetch_mod.is_read_failure_result(page.snippet):
      return True

  for source in brief.searches:
    if source.url:
      return True
    if source.snippet and not fetch_mod.is_search_failure_result(source.snippet):
      return True

  return False


def highlight_versions(text: str) -> str:
  """Wrap bare version numbers and date-stamped API versions in backticks."""
  if not text:
    return text
  return _VERSION_RE.sub(r"`\1`", text)


def _render_bullet_list(items: list[str]) -> list[str]:
  return [f"- {highlight_versions(item)}" for item in items if item.strip()]


def finalize_brief(brief: ResearchBrief) -> ResearchBrief:
  """Add a research-unavailable note when no usable live research was gathered."""
  if not has_usable_research(brief):
    if RESEARCH_UNAVAILABLE_NOTE not in brief.notes:
      brief.add_note(RESEARCH_UNAVAILABLE_NOTE)
  return brief


def render_to_system(brief: ResearchBrief) -> str:
  """Render a research brief as a system-context block for downstream completions."""
  sections = ["<research_brief>"]

  if brief.query:
    sections.append(f"<query>{brief.query}</query>")

  if brief.searches:
    sections.append("<search_results>")
    for idx, source in enumerate(brief.searches, start=1):
      header = f"{idx}. {source.title}"
      if source.url:
        header += f" ({source.url})"
      sections.append(header)
      if source.snippet:
        sections.append(source.snippet)
    sections.append("</search_results>")

  if brief.pages:
    sections.append("<page_content>")
    for source in brief.pages:
      header = source.title
      if source.url:
        header += f" — {source.url}"
      sections.append(header)
      if source.snippet:
        sections.append(source.snippet)
    sections.append("</page_content>")

  if brief.notes:
    sections.append("<notes>")
    for idx, note in enumerate(brief.notes, start=1):
      sections.append(f"{idx}. {note}")
    sections.append("</notes>")

  if brief.facts:
    sections.append("<facts>")
    sections.extend(_render_bullet_list(brief.facts))
    sections.append("</facts>")

  if brief.uncertainties:
    sections.append("<uncertainties>")
    sections.extend(_render_bullet_list(brief.uncertainties))
    sections.append("</uncertainties>")

  if brief.recommendation:
    recommendation = highlight_versions(brief.recommendation.strip())
    sections.append(f"<recommendation>{recommendation}</recommendation>")

  if brief.do_not_assume:
    sections.append("<do_not_assume>")
    sections.extend(_render_bullet_list(brief.do_not_assume))
    sections.append("</do_not_assume>")

  sections.append("</research_brief>")
  return "\n".join(sections)