import re
import requests

url_regex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
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


async def apply(chat, llm):
  text = chat.text()
  urls = re.findall(url_regex, text)

  # No - URLs - proceed as usual
  if len(urls) == 0:
    return await llm.stream_final_completion()

  # Yes - URLs - read them
  content = ""
  for url in urls:
    await llm.emit_status(f"Reading {url[0]}...")
    content += requests.get(url[0]).text

  await llm.stream_final_completion(
    prompt=prompt,
    content=content,
    request=chat.tail.content,
  )
