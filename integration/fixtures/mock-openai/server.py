import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 8080))

MODELS_RESPONSE = {
    "object": "list",
    "data": [
        {"id": "mock-model", "object": "model", "created": 1677610602, "owned_by": "mock"}
    ],
}

CHAT_RESPONSE = {
    "id": "mock-chatcmpl-001",
    "object": "chat.completion",
    "created": 1677610602,
    "model": "mock-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from mock-openai!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{self.command} {self.path} - {format % args}", flush=True)

    def send_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "service": "mock-openai"})
        elif self.path == "/v1/models":
            self.send_json(200, MODELS_RESPONSE)
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            content_len = int(self.headers.get("Content-Length", 0))
            self.rfile.read(content_len)
            self.send_json(200, CHAT_RESPONSE)
        else:
            self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"mock-openai listening on port {PORT}", flush=True)
    server.serve_forever()
