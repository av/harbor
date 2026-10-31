import re
import requests

# Bounds on what a single request can make the extractor do.
MAX_TEXT_CHARS = 100_000
MAX_URL_CHARS = 2_048
MAX_URLS = 10

TOKEN_SPLIT_RE = re.compile(r"[\s<>]+")
URL_START_RE = re.compile(r"(?i)\b(?:https?://|www\d{0,3}[.])")
BARE_DOMAIN_RE = re.compile(r"(?i)[^a-z0-9]*([a-z0-9][a-z0-9.\-]*[.][a-z]{2,4}/)")
TRAILING_PUNCTUATION = "`!()[]{};:'\".,<>?«»“”‘’"

prompt = """
<instruction>
Your task is to fulfill the user's request by discussing provided content.
</instruction>

<content>
{content}
</content>

<request>
{request}
</request>
""".strip()

ID_PREFIX = "discussurl"


def _url_starts(token):
  bare = BARE_DOMAIN_RE.match(token)
  if bare:
    yield bare.start(1), bare.end(1)
  for match in URL_START_RE.finditer(token):
    yield match.start(), match.end()


def _url_end(token, start, body):
  """
  Returns where the URL starting at `start` ends (None when it is longer than
  MAX_URL_CHARS) and where scanning stopped. A URL stops at an unbalanced ")"
  or before an unclosed "(", and does not end with punctuation.
  """
  limit = min(len(token), start + MAX_URL_CHARS)
  opened = []
  stop = limit
  for i in range(body, limit):
    if token[i] == "(":
      opened.append(i)
    elif token[i] == ")":
      if not opened:
        stop = i
        break
      opened.pop()
  else:
    if limit < len(token):
      return None, limit

  end = opened[0] if opened else stop
  while end > body and token[end - 1] in TRAILING_PUNCTUATION and token[end - 1] != ")":
    end -= 1
  return end, stop


def extract_urls(text):
  """
  Finds URLs in linear time. Only the last MAX_TEXT_CHARS of the text are
  scanned and at most MAX_URLS URLs are returned.
  """
  tokens = TOKEN_SPLIT_RE.split(text[-MAX_TEXT_CHARS:])
  if len(text) > MAX_TEXT_CHARS:
    # The first token may be cut mid-URL
    tokens = tokens[1:]

  urls = []
  for token in tokens:
    scanned = 0
    for start, body in _url_starts(token):
      if start < scanned:
        continue
      end, scanned = _url_end(token, start, body)
      if end is not None and end > body:
        urls.append(token[start:end])
        if len(urls) == MAX_URLS:
          return urls
  return urls


async def apply(chat, llm):
  """
  Matches all URLs in the input, reads them with Jina and adds their content for
  the LLM to use during the completion.
  """

  text = chat.text()
  urls = extract_urls(text)

  # No - URLs - proceed as usual
  if len(urls) == 0:
    return await llm.stream_final_completion()

  # Yes - URLs - read them
  content = ""
  for url in urls:
    await llm.emit_status(f"Reading {url}...")
    content += requests.get('https://r.jina.ai/' + url).text

  await llm.stream_final_completion(
    prompt=prompt,
    content=content,
    request=chat.tail.content,
  )
