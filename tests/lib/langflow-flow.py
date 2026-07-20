#!/usr/bin/env python3
"""Langflow flow-execution check for tests/services-integration.sh (I10).

Builds a minimal ChatInput -> ChatOutput passthrough flow from the live
component catalog (so node templates always match the running version),
imports it via POST /api/v1/flows, executes it via POST /api/v1/run/{id}
(which requires an x-api-key, minted here), prints the flow output text,
and deletes the flow again.

Usage: langflow-flow.py <base_url> <access_token>
Exit 0 with the output text on stdout; nonzero on any failure.
"""

import gzip
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/")
TOK = sys.argv[2]


def req(path, data=None, method=None, headers=None):
    h = {
        "Authorization": "Bearer " + TOK,
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
    }
    h.update(headers or {})
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=h,
        method=method or ("POST" if data is not None else "GET"),
    )
    with urllib.request.urlopen(r, timeout=120) as resp:
        body = resp.read()
    # Some langflow endpoints gzip regardless of Accept-Encoding.
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body) if body else None


catalog = req("/api/v1/all")
io = catalog["input_output"]

in_id, out_id = "ChatInput-svcit", "ChatOutput-svcit"
nodes = [
    {
        "id": nid,
        "type": "genericNode",
        "position": {"x": 0 if ntype == "ChatInput" else 400, "y": 0},
        "data": {"type": ntype, "id": nid, "node": io[ntype]},
    }
    for nid, ntype in ((in_id, "ChatInput"), (out_id, "ChatOutput"))
]

src_handle = {
    "dataType": "ChatInput",
    "id": in_id,
    "name": "message",
    "output_types": ["Message"],
}
tgt_handle = {
    "fieldName": "input_value",
    "id": out_id,
    "inputTypes": io["ChatOutput"]["template"]["input_value"]["input_types"],
    "type": "str",
}


def enc(handle):
    # React-flow handle ids use œ in place of quotes.
    return json.dumps(handle).replace('"', "œ")


edge = {
    "id": "edge-svcit",
    "source": in_id,
    "target": out_id,
    "sourceHandle": enc(src_handle),
    "targetHandle": enc(tgt_handle),
    "data": {"sourceHandle": src_handle, "targetHandle": tgt_handle},
}

flow = {
    "name": "services-it-passthrough",
    "description": "harbor services integration test flow",
    "data": {"nodes": nodes, "edges": [edge], "viewport": {"x": 0, "y": 0, "zoom": 1}},
}

created = req("/api/v1/flows/", flow)
fid = created["id"]
print("flow_id:", fid, file=sys.stderr)

try:
    api_key = req("/api/v1/api_key/", {"name": "services-it"})["api_key"]
    run = req(
        f"/api/v1/run/{fid}",
        {"input_value": "PONG-services-it", "input_type": "chat", "output_type": "chat"},
        headers={"x-api-key": api_key},
    )
    print(run["outputs"][0]["outputs"][0]["results"]["message"]["text"])
finally:
    req(f"/api/v1/flows/{fid}", method="DELETE")
