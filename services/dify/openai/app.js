import express from "express";
import bodyParser from "body-parser";
import dotenv from "dotenv";
import fetch from "node-fetch";

dotenv.config();

const config = {
  DIFY_API_URL: process.env.DIFY_API_URL,
  BOT_TYPE: process.env.BOT_TYPE || "Chat",
  INPUT_VARIABLE: process.env.INPUT_VARIABLE || "",
  OUTPUT_VARIABLE: process.env.OUTPUT_VARIABLE || "",
  PORT: process.env.PORT || 3000,
};

if (!config.DIFY_API_URL) throw new Error("DIFY API URL is required.");

const apiPaths = {
  Chat: "/v1/chat-messages",
  Completion: "/v1/completion-messages",
  Workflow: "/v1/workflows/run",
};

const apiPath = apiPaths[config.BOT_TYPE];
if (!apiPath) throw new Error("Invalid bot type in the environment variable.");

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers":
    "DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization",
  "Access-Control-Max-Age": "86400",
};

const generateId = () =>
  [...Array(29)].map(() => Math.random().toString(36)[2]).join('');

const createRequestBody = (messages, queryString) => ({
  ...(config.INPUT_VARIABLE
    ? { inputs: { [config.INPUT_VARIABLE]: queryString } }
    : { inputs: {}, query: queryString }),
  response_mode: "streaming",
  // conversation_id: "",
  user: "apiuser",
  auto_generate_name: false,
});

const handleStreamResponse = async (res, stream, data) => {
  res.setHeader("Content-Type", "text/event-stream");
  let buffer = "";
  let isFirstChunk = true;
  let isResponseEnded = false;

  const writeChunk = (chunkContent, isEnd = false) => {
    if (isResponseEnded) return;
    const chunkObj = {
      id: `chatcmpl-${Date.now()}`,
      object: "chat.completion.chunk",
      created: Date.now(),
      model: data.model,
      choices: [
        {
          index: 0,
          delta: isEnd ? {} : { content: chunkContent },
          finish_reason: isEnd ? "stop" : null,
        },
      ],
    };
    res.write(`data: ${JSON.stringify(chunkObj)}\n\n`);
    console.log('Received from Dify API:', JSON.stringify(chunkObj));
    if (isEnd) {
      res.write("data: [DONE]\n\n");
      res.end();
      isResponseEnded = true;
    }
  };

  for await (const chunk of stream) {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      let chunkObj;
      try {
        chunkObj = JSON.parse(line.slice(5).trim());
      } catch (error) {
        console.error("Error parsing chunk:", error);
        continue;
      }

      console.log('Received from Dify API:', JSON.stringify(chunkObj));

      switch (chunkObj.event) {
        case "message":
        case "agent_message":
        case "text_chunk":
          let chunkContent =
            chunkObj.event === "text_chunk"
              ? chunkObj.data.text
              : chunkObj.answer;
          if (isFirstChunk) {
            chunkContent = chunkContent.trimStart();
            isFirstChunk = false;
          }
          if (chunkContent !== "") writeChunk(chunkContent);
          break;
        case "workflow_finished":
        case "message_end":
          writeChunk("", true);
          break;
        case "error":
          console.error(`Error: ${chunkObj.code}, ${chunkObj.message}`);
          res
            .status(500)
            .write(`data: ${JSON.stringify({ error: chunkObj.message })}\n\n`);
          writeChunk("", true);
          break;
      }
    }
  }
};

const handleNonStreamResponse = async (res, stream, data) => {
  let result = "";
  let usageData = null;
  let hasError = false;

  try {
    for await (const chunk of stream) {
      const lines = chunk.toString().split('\n').filter(line => line.trim() !== '');

      for (let line of lines) {
        if (line.startsWith('data:')) {
          line = line.slice(5).trim();
        }
        const jsonStr = line;
        if (jsonStr === '[DONE]') continue;

        try {
          const chunkObj = JSON.parse(jsonStr);
          console.log('Received from Dify API:', JSON.stringify(chunkObj));

          if (
            chunkObj.event === "message" ||
            chunkObj.event === "agent_message"
          ) {
            result += chunkObj.answer;
          } else if (chunkObj.event === "message_end") {
            usageData = {
              prompt_tokens: chunkObj.metadata.usage.prompt_tokens || 100,
              completion_tokens:
                chunkObj.metadata.usage.completion_tokens || 10,
              total_tokens: chunkObj.metadata.usage.total_tokens || 110,
            };
          } else if (chunkObj.event === "workflow_finished") {
            const outputs = chunkObj.data.outputs;
            result = outputs;
            result = String(result);
            usageData = {
              prompt_tokens: chunkObj.metadata?.usage?.prompt_tokens || 100,
              completion_tokens: chunkObj.metadata?.usage?.completion_tokens || 10,
              total_tokens: chunkObj.data.total_tokens || 110,
            };
          } else if (chunkObj.event === "agent_thought") {
          } else if (chunkObj.event === "ping") {
          } else if (chunkObj.event === "error") {
            console.error(`Error: ${chunkObj.code}, ${chunkObj.message}`);
            hasError = true;
            break;
          }
        } catch (err) {
          console.error('Error parsing chunk:', err);
          hasError = true;
        }
      }
    }

    if (hasError) {
      throw new Error('An error occurred while processing the stream');
    }

    if (!result) {
      throw new Error('No result was generated');
    }

    const formattedResponse = {
      id: `chatcmpl-${generateId()}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: data.model,
      choices: [
        {
          index: 0,
          message: {
            role: "assistant",
            content: result.trim(),
          },
          finish_reason: "stop",
        },
      ],
      usage: usageData,
    };

    console.log('Sent to client:', JSON.stringify(formattedResponse));
    res.json(formattedResponse);
  } catch (error) {
    console.error('Error in handleNonStreamResponse:', error);
    res.status(500).json({ error: error.message || "An error occurred while processing the request." });
  }
};

const app = express();
app.use(bodyParser.json());

app.use((req, res, next) => {
  res.set(corsHeaders);
  if (req.method === "OPTIONS") return res.status(204).end();
  console.log("Request Method:", req.method, "Request Path:", req.path);
  next();
});

app.get("/", (_, res) => {
  res.send(`
    <html>
      <head><title>DIFY2OPENAI</title></head>
      <body>
        <h1>Dify2OpenAI</h1>
        <p>Congratulations! Your project has been successfully deployed.</p>
      </body>
    </html>
  `);
});

app.post("/v1/chat/completions", async (req, res) => {
  const authHeader = req.headers.authorization;

  if (!authHeader?.split(" ")[1]) {
    return res.status(401).json({ code: 401, errmsg: "Unauthorized." });
  }

  try {
    const { messages, stream = false, model } = req.body;
    const queryString =
      config.BOT_TYPE === "Chat"
        ? `here is our talk history:\n'''\n${messages
            .slice(0, -1)
            .map((m) => `${m.role}: ${m.content}`)
            .join("\n")}\n'''\n\nhere is my question:\n${messages[messages.length - 1].content}`
        : messages[messages.length - 1].content;

    const requestBody = {
      ...createRequestBody(messages, queryString),
      response_mode: stream ? "streaming" : "blocking",
    };

    const url = `${config.DIFY_API_URL}${apiPath}`;
    const fetchOptions = {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: authHeader,
      },
      body: JSON.stringify(requestBody),
    };

    console.log('Sent to Dify API:', JSON.stringify(requestBody));

    const resp = await fetch(url, fetchOptions);

    if (!resp.ok) {
      throw new Error(`Dify API responded with status ${resp.status}`);
    }

    stream
      ? await handleStreamResponse(res, resp.body, { model })
      : await handleNonStreamResponse(res, resp.body, { model });
  } catch (error) {
    console.error("Error:", error);
    res
      .status(500)
      .json({ error: error.message || "An error occurred while processing the request." });
  }
});

app.get('/v1/models', async (req, res) => {
  res.status(200).json({
    "data": [
      {
        "id": "dify",
        "object": "model",
        "created": Date.now() / 1000,
        "owned_by": "dify"
      }
    ],
    "object": "list"
  });
});

app.listen(config.PORT, () => console.log(`Server running on port ${config.PORT}`));

process.on('SIGINT', () => {
  console.info("Interrupted")
  process.exit(0)
});