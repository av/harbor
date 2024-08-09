from flask import Flask, request, jsonify, Response, stream_with_context
from pydantic import BaseModel
from typing import List, Optional
from airllm import AutoModel

import json
import time
import uuid
import os

# Initialize Flask app
app = Flask(__name__)
model = None

import os

# Read from the environment or use defaults
MAX_LENGTH = int(os.getenv('MAX_LENGTH', 128))
PORT = int(os.getenv('PORT', 5000))
MODEL_ID = os.getenv('MODEL_ID', "meta-llama/Meta-Llama-3.1-8B-Instruct")
COMPRESSION = os.getenv('COMPRESSION', '4bit')

# Request model schema for `/v1/completions`
class CompletionRequestBody(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 20
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stop: Optional[List[str]] = None

# Request model schema for `/v1/chat/completions`
class ChatCompletionRequestBody(BaseModel):
    messages: List[dict]
    max_tokens: Optional[int] = 128
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stop: Optional[List[str]] = None

# `/v1/models` endpoint
@app.route("/v1/models", methods=["GET"])
def list_models():
    response = {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 1234567890,
                "owned_by": "organization",
                "permission": []
            }
        ]
    }
    return jsonify(response)

# `/v1/chat/completions` endpoint with streaming support
@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    try:
        # Parse the incoming request
        data = request.get_json()
        req_body = ChatCompletionRequestBody(**data)

        # Concatenate the messages into a single prompt
        prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in req_body.messages])

        prompt = model.tokenizer.apply_chat_template(
            req_body.messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        # Tokenize the input prompt
        input_tokens = model.tokenizer(
            [prompt],
            return_tensors="pt",
            return_attention_mask=False,
            truncation=True,
            max_length=MAX_LENGTH,
            padding=False
        )

        input_ids = input_tokens['input_ids'].cuda()

        # Generate the output sequence with streaming
        gen_output = model.generate(
            input_ids,
            max_new_tokens=req_body.max_tokens,
            use_cache=True,
            return_dict_in_generate=True,
            output_scores=True,
            pad_token_id=model.tokenizer.eos_token_id
        )

        # Extract the generated tokens (when return_dict_in_generate=True)
        generated_sequences = gen_output['sequences']

        def generate_stream():
            # Decode tokens one by one and stream the response
            for i in range(input_ids.shape[1], generated_sequences.shape[1]):
                token = generated_sequences[:, i:i+1]
                output_text = model.tokenizer.decode(token[0], skip_special_tokens=True)

                # Simulating a slight delay to demonstrate streaming (remove in production)
                time.sleep(0.1)

                if output_text.strip():  # Only stream non-empty content
                    chunk = {
                        "id": f"chatcmpl-xxxx",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": MODEL_ID,
                        "system_fingerprint": "fp_airllm",
                        "choices": [
                            {
                                "delta": {
                                    "role": "assistant",
                                    "content": output_text
                                },
                                "index": 0,
                                "finish_reason": None
                            }
                        ]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            # Stream the final stop signal
            final_chunk = {
                "id": f"chatcmpl-xxxx",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_ID,
                "system_fingerprint": "fp_airllm",
                "choices": [
                    {
                        "delta": {},
                        "index": 0,
                        "finish_reason": "stop"
                    }
                ]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"

        return Response(stream_with_context(generate_stream()), content_type='text/event-stream')

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print(f"Config: PORT={PORT} MODEL={MODEL_ID} MAX_LENGTH={MAX_LENGTH}")
    print(f"Loading model...")

    if COMPRESSION == 'none':
        model = AutoModel.from_pretrained(
            MODEL_ID
        )
    else:
        model = AutoModel.from_pretrained(
            MODEL_ID,
            compression=COMPRESSION
        )

    print(f"Starting server on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
