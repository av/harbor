#!/usr/bin/env python3
"""
Harbor openfang proxy — localhost spoofing + agent manifest patching.

Listens on 0.0.0.0:4200, forwards to 127.0.0.1:{OPENFANG_PORT}.
Rewrites the [model] section of agent manifests on POST /api/agents
so agents use Harbor's configured provider instead of the UI default.
"""

import http.client
import http.server
import json
import os
import signal
import socket
import socketserver
import threading
import tomllib

OPENFANG_HOST = "127.0.0.1"
OPENFANG_PORT = int(os.environ.get("HARBOR_OPENFANG_INTERNAL_PORT", "4201"))
LISTEN_PORT = 4200
BUF = 65536

HARBOR_PROVIDER = os.environ.get("HARBOR_OPENFANG_MODEL_PROVIDER", "ollama")
HARBOR_MODEL = os.environ.get("HARBOR_OPENFANG_MODEL", "")
HARBOR_BASE_URL = os.environ.get("HARBOR_OPENFANG_BASE_URL", "")
HARBOR_VERSION = os.environ.get("HARBOR_OPENFANG_VERSION", "").lstrip("v")


def _toml_dumps(data: dict) -> str:
    """Minimal TOML serializer for flat tables with scalar values."""
    lines = []
    scalars = {}
    tables = {}
    for k, v in data.items():
        if isinstance(v, dict):
            tables[k] = v
        else:
            scalars[k] = v

    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_encode(v)}")
    if scalars and tables:
        lines.append("")

    for section, vals in tables.items():
        lines.append(f"[{section}]")
        for k, v in vals.items():
            lines.append(f"{k} = {_toml_encode(v)}")
        lines.append("")

    return "\n".join(lines) + ("\n" if lines else "")


def _toml_encode(v) -> str:
    if isinstance(v, str):
        return json.dumps(v)  # JSON string encoding is valid TOML
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_encode(i) for i in v) + "]"
    raise TypeError(f"unsupported TOML type: {type(v)}")


def _patch_manifest(manifest_toml: str) -> str:
    """Parse manifest TOML, replace [model] section, serialize back."""
    data = tomllib.loads(manifest_toml)
    model = {"provider": HARBOR_PROVIDER}
    if HARBOR_MODEL:
        model["model"] = HARBOR_MODEL
    if HARBOR_BASE_URL:
        model["base_url"] = HARBOR_BASE_URL
    data["model"] = model
    return _toml_dumps(data)


def _relay(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(BUF)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    for s in (src, dst):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    server_version = "harbor-openfang-proxy"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # Route all methods through the proxy
    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_OPTIONS(self):
        self._dispatch()

    def _dispatch(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket()
        elif (
            self.command == "POST"
            and self.path.rstrip("/").split("?")[0] == "/api/agents"
        ):
            self._proxy_agents()
        elif (
            self.command == "GET"
            and self.path.rstrip("/").split("?")[0] == "/api/status"
        ):
            self._proxy_status()
        else:
            self._proxy()

    def _read_request_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _upstream_headers(self) -> dict[str, str]:
        headers = {}
        for key, val in self.headers.items():
            if key.lower() in ("accept-encoding", "host"):
                continue
            headers[key] = val
        return headers

    def _proxy(self):
        body = self._read_request_body()
        try:
            conn = http.client.HTTPConnection(OPENFANG_HOST, OPENFANG_PORT)
            try:
                conn.request(
                    self.command,
                    self.path,
                    body=body if body else None,
                    headers=self._upstream_headers(),
                )
                resp = conn.getresponse()
                self._forward_response(resp)
            finally:
                conn.close()
        except Exception:
            try:
                self.send_error(502)
            except Exception:
                pass

    def _proxy_status(self):
        """Proxy /api/status and inject version if missing."""
        body = self._read_request_body()
        try:
            conn = http.client.HTTPConnection(OPENFANG_HOST, OPENFANG_PORT)
            try:
                conn.request(
                    self.command,
                    self.path,
                    body=body if body else None,
                    headers=self._upstream_headers(),
                )
                resp = conn.getresponse()
                raw = resp.read()
                try:
                    data = json.loads(raw)
                    if "version" not in data and HARBOR_VERSION:
                        data["version"] = HARBOR_VERSION
                        raw = json.dumps(data).encode()
                except Exception:
                    pass
                self.send_response_only(resp.status, resp.reason)
                for key, val in resp.getheaders():
                    if key.lower() in self._STRIPPED_HEADERS:
                        continue
                    self.send_header(key, val)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if raw:
                    self.wfile.write(raw)
            finally:
                conn.close()
        except Exception:
            try:
                self.send_error(502)
            except Exception:
                pass

    def _proxy_agents(self):
        body = self._read_request_body()
        try:
            data = json.loads(body)
            if "manifest_toml" in data:
                data["manifest_toml"] = _patch_manifest(data["manifest_toml"])
                body = json.dumps(data).encode()
        except Exception:
            pass

        try:
            headers = self._upstream_headers()
            headers["Content-Length"] = str(len(body))
            conn = http.client.HTTPConnection(OPENFANG_HOST, OPENFANG_PORT)
            try:
                conn.request("POST", self.path, body=body, headers=headers)
                resp = conn.getresponse()
                self._forward_response(resp)
            finally:
                conn.close()
        except Exception:
            try:
                self.send_error(502)
            except Exception:
                pass

    _STRIPPED_HEADERS = frozenset(
        ("transfer-encoding", "content-encoding", "content-length")
    )

    def _forward_response(self, resp: http.client.HTTPResponse):
        self.send_response_only(resp.status, resp.reason)

        is_streaming = False
        for key, val in resp.getheaders():
            kl = key.lower()
            if kl in self._STRIPPED_HEADERS:
                if kl == "transfer-encoding" and "chunked" in val.lower():
                    is_streaming = True
                continue
            if kl == "content-type" and "event-stream" in val.lower():
                is_streaming = True
            self.send_header(key, val)

        if self.command == "HEAD":
            self.end_headers()
            return

        if is_streaming:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(BUF)
                if not chunk:
                    break
                self.wfile.write(f"{len(chunk):x}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        else:
            data = resp.read()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

    def _handle_websocket(self):
        """Reconstruct raw HTTP request and relay via raw sockets."""
        raw_req = f"{self.command} {self.path} {self.request_version}\r\n"
        for key in self.headers:
            for val in self.headers.get_all(key) or []:
                raw_req += f"{key}: {val}\r\n"
        raw_req += "\r\n"

        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            upstream.connect((OPENFANG_HOST, OPENFANG_PORT))
            upstream.sendall(raw_req.encode())

            # Read upstream response headers
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = upstream.recv(BUF)
                if not chunk:
                    self.send_error(502)
                    upstream.close()
                    return
                buf += chunk

            sep = buf.index(b"\r\n\r\n") + 4
            resp_head = buf[:sep]
            resp_extra = buf[sep:]

            status_line = resp_head.split(b"\r\n")[0].decode("utf-8", errors="replace")
            parts = status_line.split()
            status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

            if status_code == 101:
                # Successful upgrade — send 101 to client, then relay raw TCP
                client_sock = self.request
                client_sock.sendall(resp_head + resp_extra)
                t = threading.Thread(
                    target=_relay, args=(upstream, client_sock), daemon=True
                )
                t.start()
                _relay(client_sock, upstream)
            else:
                # Upgrade rejected — send the response back normally
                self.wfile.write(resp_head + resp_extra)
                # Drain any remaining response body
                while True:
                    chunk = upstream.recv(BUF)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                upstream.close()
        except Exception:
            try:
                upstream.close()
            except Exception:
                pass
            try:
                self.send_error(502)
            except Exception:
                pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    server = ThreadedHTTPServer(("0.0.0.0", LISTEN_PORT), ProxyHandler)

    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()
