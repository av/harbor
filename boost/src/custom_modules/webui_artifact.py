import chat as ch
import llm

ID_PREFIX='webui_artifact'

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_message("""
```html
<!DOCTYPE html>
<html lang="en">
  <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Hi</title>
  </head>
  <body>
      <h1>My First Heading</h1>
      <p>My first paragraph.</p>
  </body>
</html>
```
  """)

  await llm.emit_message("""

```html
<!DOCTYPE html>
<html lang="en">
  <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Hi</title>
  </head>
  <body>
      <h1>My second Heading</h1>
      <p>My second paragraph.</p>
  </body>
</html>
```

  """)

#   await llm.emit_message("""
# ```css
# body {
#   background-color: lightblue;
# }

# h1 {
#   color: white;
#   text-align: center;
# }
# ```
#   """)

#   await llm.emit_message("""
# ```javascript
# document.getElementById("demo").innerHTML = "Hello JavaScript!";
# ```
#   """)

  await llm.stream_final_completion()