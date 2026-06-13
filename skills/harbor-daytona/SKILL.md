---
name: harbor-daytona
description: Use Harbor's Daytona sandbox platform for computer use — creating sandboxes, taking screenshots, sending mouse/keyboard input, and building agent loops. Use when the user wants to interact with a GUI, automate a desktop, do computer use, control a browser visually, or run Claude computer use against a Daytona sandbox.
allowed-tools: Bash(curl:*), Bash(python3:*), Bash(harbor:*), Bash(docker:*), Bash(file:*), Bash(base64:*), Read(*), Write(*)
---

# Harbor Daytona: Computer Use

Daytona is a self-hosted sandbox platform running inside Harbor. Each sandbox provides an isolated Linux environment with a full XFCE4 desktop (Xvfb + x11vnc + noVNC) controllable via REST API — screenshot, mouse, keyboard, process management.

## Quick Start

```bash
# Start the Daytona platform (14 containers)
harbor up daytona

# Verify it's healthy
harbor ps | grep daytona
```

Dashboard: `http://localhost:$(harbor config get daytona.host_port)/dashboard`
Default credentials: `dev@daytona.io` / `password` (via Dex OIDC; login is by email)

## Auth

All API calls use the admin API key as a Bearer token:

```bash
API_KEY=$(harbor config get daytona.admin_api_key)
AUTH="Authorization: Bearer $API_KEY"
API="http://localhost:$(harbor config get daytona.host_port)"
```

Default key: `harbor-daytona-admin-key`

## Sandbox Lifecycle

### Create a sandbox

```bash
curl -s -X POST "$API/api/sandbox" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "snapshot": "daytonaio/sandbox:v0.185.0-amd64",
    "user": "daytona",
    "cpu": 2,
    "memory": 4,
    "disk": 10,
    "autoStopInterval": 30
  }'
```

The response includes the sandbox `id` — use it in all subsequent calls. The sandbox starts in `"state": "creating"` and transitions to `"started"` (typically 20-30 seconds).

CreateSandbox fields: `name`, `snapshot`, `user`, `env` (object), `labels` (object), `public` (bool), `cpu`, `gpu`, `memory` (GB), `disk` (GB), `autoStopInterval` (minutes, 0=disabled), `autoArchiveInterval`, `autoDeleteInterval` (-1=disabled), `target` ("us"), `volumes`, `linkedSandbox`.

### Poll until started

```bash
STATE=""
while [ "$STATE" != "started" ]; do
  STATE=$(curl -s "$API/api/sandbox/$SANDBOX_ID" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  sleep 2
done
```

### Other lifecycle operations

```bash
# List sandboxes
curl -s "$API/api/sandbox" -H "$AUTH"

# Get sandbox details
curl -s "$API/api/sandbox/$SANDBOX_ID" -H "$AUTH"

# Stop / start / delete
curl -s -X POST "$API/api/sandbox/$SANDBOX_ID/stop" -H "$AUTH"
curl -s -X POST "$API/api/sandbox/$SANDBOX_ID/start" -H "$AUTH"
curl -s -X DELETE "$API/api/sandbox/$SANDBOX_ID" -H "$AUTH"
```

## Computer Use API

Base URL: `$API/api/toolbox/$SANDBOX_ID/toolbox/computeruse`

### Start the desktop

Computer use processes must be started before taking screenshots or sending input. The default snapshot boots them automatically but they may be in `"partial"` state.

```bash
# Check status — returns {"status": "active"|"partial"|"inactive"|"error"}
curl -s "$BASE/status" -H "$AUTH"

# Start all desktop processes (xvfb, xfce4, x11vnc, novnc, atspi)
curl -s -X POST "$BASE/start" -H "$AUTH"

# Stop desktop processes
curl -s -X POST "$BASE/stop" -H "$AUTH"
```

### Screenshot

```bash
# Full screenshot — returns {"screenshot": "<base64 PNG>", "cursorPosition": {"x","y"}, "sizeBytes": N}
curl -s "$BASE/screenshot" -H "$AUTH"

# Compressed (smaller file, lower quality)
curl -s "$BASE/screenshot/compressed" -H "$AUTH"

# Region screenshot (query params: x, y, width, height)
curl -s "$BASE/screenshot/region?x=0&y=0&width=512&height=384" -H "$AUTH"

# Compressed region
curl -s "$BASE/screenshot/region/compressed?x=0&y=0&width=512&height=384" -H "$AUTH"
```

Default resolution: 1024x768. Response is JSON with base64-encoded PNG in the `screenshot` field.

To decode and save:

```bash
curl -s "$BASE/screenshot" -H "$AUTH" | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
with open('/tmp/screenshot.png', 'wb') as f:
    f.write(base64.b64decode(data['screenshot']))
"
```

### Mouse

```bash
# Click — body: {x, y, button?: "left"|"right"|"middle", double?: bool}
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": 500, "y": 400, "button": "left"}'

# Double-click
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": 500, "y": 400, "double": true}'

# Move — body: {x, y}
curl -s -X POST "$BASE/mouse/move" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": 300, "y": 200}'

# Drag — body: {startX, startY, endX, endY, button?: "left"|"right"|"middle"}
curl -s -X POST "$BASE/mouse/drag" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"startX": 100, "startY": 200, "endX": 400, "endY": 300}'

# Scroll — body: {x, y, direction: "up"|"down", amount?: N}
curl -s -X POST "$BASE/mouse/scroll" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": 500, "y": 400, "direction": "down", "amount": 3}'

# Get position — returns {x, y}
curl -s "$BASE/mouse/position" -H "$AUTH"
```

### Keyboard

```bash
# Type text — body: {text, delay?: ms_between_keystrokes}
curl -s -X POST "$BASE/keyboard/type" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"text": "hello world"}'

# Press a single key — body: {key, modifiers?: ["ctrl","alt","shift","cmd"]}
curl -s -X POST "$BASE/keyboard/key" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"key": "Return"}'

# Key with modifiers
curl -s -X POST "$BASE/keyboard/key" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"key": "c", "modifiers": ["ctrl"]}'

# Hotkey combination — body: {keys: "modifier+key"}
curl -s -X POST "$BASE/keyboard/hotkey" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"keys": "ctrl+l"}'
```

Key names: `Return`, `Tab`, `Escape`, `BackSpace`, `Delete`, `space`, `Up`, `Down`, `Left`, `Right`, `Home`, `End`, `Page_Up`, `Page_Down`, `F1`-`F12`, plus single characters.

### Display Info

```bash
# Display geometry — returns {displays: [{id, x, y, width, height, isActive}]}
curl -s "$BASE/display/info" -H "$AUTH"

# List windows — returns {windows: [{id, title}], count: N}
curl -s "$BASE/display/windows" -H "$AUTH"
```

### Process Management

Desktop processes: `xvfb`, `xfce4`, `x11vnc`, `novnc`, `atspi`

```bash
# Status of a process — returns {processName, running: bool}
curl -s "$BASE/process/xfce4/status" -H "$AUTH"

# Logs / errors
curl -s "$BASE/process/novnc/logs" -H "$AUTH"
curl -s "$BASE/process/x11vnc/errors" -H "$AUTH"

# Restart a process
curl -s -X POST "$BASE/process/xfce4/restart" -H "$AUTH"
```

## Agent Loop Pattern

A computer use agent loop follows this cycle: screenshot -> send to model -> execute action -> repeat.

```bash
API_KEY=$(harbor config get daytona.admin_api_key)
AUTH="Authorization: Bearer $API_KEY"
API="http://localhost:$(harbor config get daytona.host_port)"

# 1. Create sandbox
SANDBOX_ID=$(curl -s -X POST "$API/api/sandbox" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"snapshot":"daytonaio/sandbox:v0.185.0-amd64","user":"daytona","cpu":2,"memory":4,"disk":10,"autoStopInterval":30}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Wait for started
while true; do
  STATE=$(curl -s "$API/api/sandbox/$SANDBOX_ID" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  [ "$STATE" = "started" ] && break
  sleep 2
done

# 3. Start desktop
BASE="$API/api/toolbox/$SANDBOX_ID/toolbox/computeruse"
curl -s -X POST "$BASE/start" -H "$AUTH"

# 4. Loop: screenshot -> decide -> act
# Take screenshot
curl -s "$BASE/screenshot" -H "$AUTH" | python3 -c "
import sys,json,base64
d=json.load(sys.stdin)
with open('/tmp/screen.png','wb') as f: f.write(base64.b64decode(d['screenshot']))
"

# Send /tmp/screen.png to the model for analysis, get back an action, then:
# - click:    curl -X POST "$BASE/mouse/click" -d '{"x":N,"y":N}'
# - type:     curl -X POST "$BASE/keyboard/type" -d '{"text":"..."}'
# - key:      curl -X POST "$BASE/keyboard/key" -d '{"key":"Return"}'
# - hotkey:   curl -X POST "$BASE/keyboard/hotkey" -d '{"keys":"ctrl+c"}'
# - scroll:   curl -X POST "$BASE/mouse/scroll" -d '{"x":N,"y":N,"direction":"down","amount":3}'

# 5. Cleanup
curl -s -X DELETE "$API/api/sandbox/$SANDBOX_ID" -H "$AUTH"
```

## Command Execution (Non-GUI)

For tasks that don't need the desktop, use the toolbox process API instead:

```bash
TBOX="$API/api/toolbox/$SANDBOX_ID/toolbox"

# Execute a command — returns stdout/stderr
curl -s -X POST "$TBOX/process/execute" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"command": "ls -la /home/daytona"}'

# File operations
curl -s "$TBOX/files?path=/home/daytona" -H "$AUTH"                    # list files
curl -s "$TBOX/files/download?path=/home/daytona/file.txt" -H "$AUTH"  # download
curl -s -X POST "$TBOX/files/upload?path=/home/daytona" -H "$AUTH" \
  -F "file=@local-file.txt"                                            # upload
```

## Troubleshooting

### Sandbox stuck in "creating"

The runner considers host disk usage. If above ~80%, sandboxes loop with "No available runners." Free disk space and restart:

```bash
docker system prune -f
harbor down daytona && rm -rf services/daytona/data/db && harbor up daytona
```

### Desktop processes not starting

```bash
# Check individual process status
curl -s "$BASE/process/xvfb/status" -H "$AUTH"
curl -s "$BASE/process/xvfb/errors" -H "$AUTH"

# Force restart
curl -s -X POST "$BASE/stop" -H "$AUTH"
curl -s -X POST "$BASE/start" -H "$AUTH"
```

### Screenshot returns empty/black

Wait 2-3 seconds after `start` for the desktop to initialize. Check that `xfce4` is running:

```bash
curl -s "$BASE/process/xfce4/status" -H "$AUTH"
```

## Ports Reference

| Port | Service |
|---|---|
| 35000 | API + Dashboard |
| 35001 | Sandbox preview proxy |
| 35002 | Runner API |
| 35003 | SSH gateway |
