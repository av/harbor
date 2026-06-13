# Harbor App Daytona Install Integration Tests

This spec covers agent-executable end-to-end verification of the Harbor App's
in-app guided install flow inside Daytona sandboxes running Ubuntu 24.04 and
Fedora 42. It adapts the Linux scenarios from `tests/app-native-setup.md`
(Test 1 Linux Ready Path and Test 5 Existing Install Detection) to the Daytona
computer-use environment so they can run without a native host. Every step and
expectation is executable by an agent from scratch with no prior session
context.

---

## Prerequisites

### 1. Start Daytona and set shared variables

```bash
harbor up daytona

export API="http://localhost:$(harbor config get daytona.host_port)"
export AUTH="Authorization: Bearer $(harbor config get daytona.admin_api_key)"
```

Default values: API port `35000`, key `harbor-daytona-admin-key`.

Verify the platform is healthy:

```bash
curl -sf "$API/api/sandbox" -H "$AUTH" | python3 -c "import sys,json; print('OK', len(json.load(sys.stdin)['items']),'sandbox(es)')"
```

Note: list endpoints (`/api/sandbox`, `/api/snapshots`) return a paginated
`{"items": [...], "nextCursor": ...}` object, not a bare array. Parsing the
top-level response as a list silently misreports counts.

Confirm `USE_SNAPSHOT_ENTRYPOINT` is set in the daytona runner. This env var
tells the runner to use the snapshot's registered entrypoint instead of
injecting `/usr/local/bin/daytona` as PID 1, which is required for systemd
sandboxes:

```bash
grep -r USE_SNAPSHOT_ENTRYPOINT services/compose.daytona.yml
# Expected: USE_SNAPSHOT_ENTRYPOINT: "true"
```

If it is missing, add it to the `environment:` block of the `daytona-runner`
service in `services/compose.daytona.yml`, then run `harbor down daytona &&
harbor up daytona`.

### 2. Serve the working-tree installer scripts and packages over HTTP

The tests launch the Harbor App with `HARBOR_APP_INSTALL_SCRIPT` and
`HARBOR_REQUIREMENTS_URL` pointing at the local working tree so that the
branch under test is validated, not GitHub main.

```bash
export DEB_PATH=$(ls app/src-tauri/target/release/bundle/deb/Harbor_*.deb | head -1)
export RPM_PATH=$(ls app/src-tauri/target/release/bundle/rpm/Harbor-*.rpm | head -1)
echo "DEB: $DEB_PATH"
echo "RPM: $RPM_PATH"
```

Both files must exist before running the tests. If either is missing, build
the packages first (see Section 4 below).

Set up the HTTP server:

```bash
mkdir -p /tmp/harbor-pkg
cp "$DEB_PATH" "$RPM_PATH" /tmp/harbor-pkg/
cp install.sh /tmp/harbor-pkg/install.sh
cp requirements.sh /tmp/harbor-pkg/requirements.sh
(cd /tmp/harbor-pkg && nohup python3 -m http.server 38777 --bind 0.0.0.0 &>/tmp/pkg-server.log &)
export HOST_IP="192.168.0.94"
export PKG_URL="http://$HOST_IP:38777"
echo "Serving packages at $PKG_URL"
curl -sf "$PKG_URL/install.sh" | head -3
curl -sf "$PKG_URL/requirements.sh" | head -3
```

The `HOST_IP` above is the host's LAN IP reachable from inside sandboxes.
Adjust if your network differs (`hostname -I | awk '{print $1}'`).

### 3. Check for required snapshots

```bash
curl -s "$API/api/snapshots" -H "$AUTH" | python3 -c "
import sys, json
snaps = json.load(sys.stdin)['items']
names = [s['name'] for s in snaps]
for n in names:
    print(n)
"
```

Look for `harbor/ubuntu-24.04-sandbox:v2.0.0` and
`harbor/fedora-42-sandbox:v2.0.0` in the output. If either is missing, build
and register it using the recipes below. If both are present, skip to
Section 5.

**Host safety warning:** the Daytona runner is a privileged container, so a
sandbox systemd can reach real host devices. The recipes below force
`multi-user.target` and mask every display manager and all units that write
host-global kernel state. Never remove those lines — a display manager booting
inside a sandbox grabs the host's virtual terminals and kills the host
desktop session.

**Rebuilding under an existing tag:** the runner's DinD does not re-pull a tag
it already holds — re-registering after a re-push silently boots the old
image. After any rebuild: deregister the snapshot, purge the stale tags inside
the runner, re-register, and verify the wrapped ref offline before booting a
sandbox:

```bash
docker exec harbor.daytona-runner sh -c \
  'docker images --format "{{.Repository}}:{{.Tag}}" | grep "sandbox:v2.0.0" | xargs -r docker rmi -f'
# after re-registering, get the snapshot ref and verify WITHOUT booting:
docker exec harbor.daytona-runner docker run --rm --entrypoint sh "<ref>" -c \
  'readlink /etc/systemd/system/default.target; test -x /usr/local/sbin/hide-host-devices.sh && echo ok'
# expected: multi-user.target and ok
```

After booting any systemd sandbox, confirm on the host that no display manager
leaked: `ps aux | grep -E "lightdm|Xorg -core" | grep -v grep` must be empty
and `cat /sys/class/tty/tty0/active` must be unchanged. Also confirm the
device-neutering layer is active inside the sandbox:

```bash
sandbox_exec "$ID" "systemctl is-active hide-host-devices; grep -cE '/dev/tty[0-9]' /proc/mounts"
# expected: active, and a count around 64
```

If any check fails, delete the sandbox immediately — it booted a stale image.
During test execution keep a host watchdog loop running that deletes all
sandboxes if a foreign display manager appears or the active VT changes.
Start it before the first `create_sandbox` call and kill it during cleanup:

```bash
nohup bash /tmp/host-watchdog.sh &>/tmp/host-watchdog.log & echo "Watchdog PID: $!"
```

#### 3a. Ubuntu 24.04 snapshot (v2.0.0)

Key properties of this image:
- No Docker packages preinstalled — install.sh must install them.
- systemd installed and running as PID 1 via `/sbin/init` entrypoint.
- User `daytona` has `sudo` but requires a password (`daytona`); no NOPASSWD line.
- `/etc/docker/daemon.json` pre-baked with `vfs` storage and iptables disabled
  (required because overlay-on-overlay fails in the sandbox kernel).
- Desktop/computer-use dependencies included.

Write `Dockerfile.ubuntu-sandbox-v2`:

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    systemd systemd-sysv dbus sudo curl wget git xterm \
    xvfb xfce4 x11vnc dbus-x11 at-spi2-core \
    libwebkit2gtk-4.1-0 libgtk-3-0 libayatana-appindicator3-1 \
    librsvg2-common novnc ca-certificates iproute2 iptables \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash daytona && echo 'daytona:daytona' | chpasswd && usermod -aG sudo daytona
RUN systemctl mask \
    systemd-remount-fs.service dev-hugepages.mount sys-fs-fuse-connections.mount \
    systemd-logind.service getty.target console-getty.service \
    systemd-udev-trigger.service systemd-udevd.service \
    systemd-random-seed.service systemd-machine-id-commit.service \
    apt-daily.timer apt-daily-upgrade.timer e2scrub_reap.service fstrim.timer \
    motd-news.timer NetworkManager-wait-online.service 2>/dev/null || true
# HOST SAFETY: Daytona launches every sandbox with Privileged:true inside a
# privileged runner, so a sandbox can reach REAL host devices and kernel
# state. A display manager inside the sandbox WILL grab the host's virtual
# terminals and kick the host desktop session off the active seat (this
# happened: lightdm, pulled in by xfce4, opened host :0). The toolbox starts
# Xvfb itself — no display manager must ever run. Likewise mask units that
# write host-global kernel state (module loading, sysctls, clock, rfkill,
# backlight).
RUN systemctl set-default multi-user.target && systemctl mask \
    lightdm.service gdm.service gdm3.service sddm.service \
    display-manager.service plymouth-quit-wait.service \
    systemd-modules-load.service systemd-sysctl.service \
    systemd-timesyncd.service systemd-rfkill.service systemd-rfkill.socket \
    systemd-backlight@.service kmod-static-nodes.service 2>/dev/null || true
# Force a direct /dev/null mask on display-manager.service. On Ubuntu, the
# above 'systemctl mask display-manager.service' resolves through the
# lightdm.service alias and writes the symlink there instead of here, so
# display-manager.service would become live if lightdm's mask were ever
# removed. This explicit ln makes display-manager.service independently masked.
RUN ln -sf /dev/null /etc/systemd/system/display-manager.service
# HOST SAFETY layer 2: neuter host display/input device nodes at boot, before
# any other unit. With Privileged:true the container /dev contains the real
# host devices; bind-mounting /dev/null over them makes a console grab
# physically impossible regardless of what gets installed later. Xvfb (used
# by the Daytona toolbox) needs none of these.
RUN printf '%s\n' '#!/bin/sh' \
    'for d in /dev/tty[0-9]* /dev/vcs* /dev/fb[0-9]*; do' \
    '  [ -e "$d" ] && mount --bind /dev/null "$d" 2>/dev/null' \
    'done' \
    'for d in /dev/dri /dev/input; do' \
    '  [ -d "$d" ] && mount -t tmpfs -o size=4k,mode=000 none "$d" 2>/dev/null' \
    'done' \
    'exit 0' > /usr/local/sbin/hide-host-devices.sh \
  && chmod +x /usr/local/sbin/hide-host-devices.sh \
  && printf '%s\n' '[Unit]' \
    'Description=Hide host display/input devices from privileged sandbox' \
    'DefaultDependencies=no' \
    'Before=sysinit.target' \
    '[Service]' \
    'Type=oneshot' \
    'ExecStart=/usr/local/sbin/hide-host-devices.sh' \
    'RemainAfterExit=yes' \
    '[Install]' \
    'WantedBy=sysinit.target' > /etc/systemd/system/hide-host-devices.service \
  && systemctl enable hide-host-devices.service
RUN echo 'daytona ALL=(ALL) ALL' > /etc/sudoers.d/daytona && chmod 440 /etc/sudoers.d/daytona
RUN mkdir -p /etc/docker && echo '{"storage-driver":"vfs","iptables":false,"ip6tables":false}' > /etc/docker/daemon.json
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/sbin/init"]
```

Build, tag, and push:

```bash
docker build -f Dockerfile.ubuntu-sandbox-v2 -t harbor/ubuntu-24.04-sandbox:v2.0.0 .
docker tag harbor/ubuntu-24.04-sandbox:v2.0.0 localhost:35009/daytona/ubuntu-24.04-sandbox:v2.0.0
docker push localhost:35009/daytona/ubuntu-24.04-sandbox:v2.0.0
```

Register snapshot and wait for it to become active. The `entrypoint` field
is required — the runner ignores the Dockerfile ENTRYPOINT and only uses the
field from this API call:

```bash
SNAP_ID=$(curl -s -X POST "$API/api/snapshots" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "name": "harbor/ubuntu-24.04-sandbox:v2.0.0",
    "imageName": "daytona-registry:6000/daytona/ubuntu-24.04-sandbox:v2.0.0",
    "cpu": 2,
    "memory": 4,
    "disk": 15,
    "entrypoint": ["/sbin/init"]
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

while true; do
  STATE=$(curl -s "$API/api/snapshots/$SNAP_ID" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  echo "snapshot state: $STATE"
  [ "$STATE" = "active" ] && break
  sleep 5
done
echo "Snapshot ready: $SNAP_ID"
```

#### 3b. Fedora 42 snapshot (v2.0.0)

Same constraints as Ubuntu but using dnf and Fedora package names. `procps-ng`
and `which` are also required.

Write `Dockerfile.fedora-sandbox-v2`:

```dockerfile
FROM fedora:42
RUN dnf install -y \
    systemd dbus sudo curl wget git xterm \
    xorg-x11-server-Xvfb xfce4-session xfce4-terminal x11vnc novnc \
    dbus-x11 at-spi2-core \
    webkit2gtk4.1 gtk3 libayatana-appindicator-gtk3 librsvg2 \
    ca-certificates iproute iptables \
    procps-ng which \
  && dnf clean all
RUN useradd -m -s /bin/bash daytona && echo 'daytona:daytona' | chpasswd && usermod -aG wheel daytona
RUN systemctl mask \
    systemd-remount-fs.service dev-hugepages.mount sys-fs-fuse-connections.mount \
    systemd-logind.service getty.target console-getty.service \
    systemd-udev-trigger.service systemd-udevd.service \
    systemd-random-seed.service systemd-machine-id-commit.service \
    NetworkManager-wait-online.service 2>/dev/null || true
# HOST SAFETY: see the Ubuntu recipe — no display manager may run in a
# privileged-runner sandbox (host VT grab), and units writing host-global
# kernel state must be masked.
RUN systemctl set-default multi-user.target && systemctl mask \
    lightdm.service gdm.service sddm.service \
    display-manager.service plymouth-quit-wait.service \
    systemd-modules-load.service systemd-sysctl.service \
    systemd-timesyncd.service systemd-rfkill.service systemd-rfkill.socket \
    systemd-backlight@.service kmod-static-nodes.service 2>/dev/null || true
# HOST SAFETY layer 2: see the Ubuntu recipe — neuter host display/input
# devices at boot so a console grab is physically impossible.
RUN printf '%s\n' '#!/bin/sh' \
    'for d in /dev/tty[0-9]* /dev/vcs* /dev/fb[0-9]*; do' \
    '  [ -e "$d" ] && mount --bind /dev/null "$d" 2>/dev/null' \
    'done' \
    'for d in /dev/dri /dev/input; do' \
    '  [ -d "$d" ] && mount -t tmpfs -o size=4k,mode=000 none "$d" 2>/dev/null' \
    'done' \
    'exit 0' > /usr/local/sbin/hide-host-devices.sh \
  && chmod +x /usr/local/sbin/hide-host-devices.sh \
  && printf '%s\n' '[Unit]' \
    'Description=Hide host display/input devices from privileged sandbox' \
    'DefaultDependencies=no' \
    'Before=sysinit.target' \
    '[Service]' \
    'Type=oneshot' \
    'ExecStart=/usr/local/sbin/hide-host-devices.sh' \
    'RemainAfterExit=yes' \
    '[Install]' \
    'WantedBy=sysinit.target' > /etc/systemd/system/hide-host-devices.service \
  && systemctl enable hide-host-devices.service
RUN echo 'daytona ALL=(ALL) ALL' > /etc/sudoers.d/daytona && chmod 440 /etc/sudoers.d/daytona
RUN mkdir -p /etc/docker && echo '{"storage-driver":"vfs","iptables":false,"ip6tables":false}' > /etc/docker/daemon.json
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/sbin/init"]
```

Build, tag, push, and register:

```bash
docker build -f Dockerfile.fedora-sandbox-v2 -t harbor/fedora-42-sandbox:v2.0.0 .
docker tag harbor/fedora-42-sandbox:v2.0.0 localhost:35009/daytona/fedora-42-sandbox:v2.0.0
docker push localhost:35009/daytona/fedora-42-sandbox:v2.0.0

SNAP_ID=$(curl -s -X POST "$API/api/snapshots" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "name": "harbor/fedora-42-sandbox:v2.0.0",
    "imageName": "daytona-registry:6000/daytona/fedora-42-sandbox:v2.0.0",
    "cpu": 2,
    "memory": 4,
    "disk": 15,
    "entrypoint": ["/sbin/init"]
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

while true; do
  STATE=$(curl -s "$API/api/snapshots/$SNAP_ID" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  echo "snapshot state: $STATE"
  [ "$STATE" = "active" ] && break
  sleep 5
done
echo "Snapshot ready: $SNAP_ID"
```

### 4. Build the Harbor App packages (if not already built)

On the host machine (requires the `app/` source tree):

```bash
cd app
TAURI_LINUX_AYATANA_APPINDICATOR=1 PKG_CONFIG_PATH="$HOME/.local/lib/pkgconfig" \
  npx tauri build --bundles rpm,deb
```

Pre-built packages are at:

```
app/src-tauri/target/release/bundle/deb/Harbor_0.4.19_amd64.deb
app/src-tauri/target/release/bundle/rpm/Harbor-0.4.19-1.x86_64.rpm
```

### 5. Helper: create a sandbox and wait for it to start

The function below is referenced by all tests. Define it once in the shell:

```bash
create_sandbox() {
  local SNAPSHOT="$1"
  local SB_ID
  SB_ID=$(curl -s -X POST "$API/api/sandbox" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"snapshot\":\"$SNAPSHOT\",\"user\":\"daytona\",\"autoStopInterval\":0}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "Sandbox created: $SB_ID"
  while true; do
    STATE=$(curl -s "$API/api/sandbox/$SB_ID" -H "$AUTH" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
    [ "$STATE" = "started" ] && break
    sleep 3
  done
  echo "$SB_ID"
}
```

Note: the `POST /api/sandbox` body must NOT include `cpu`/`memory`/`disk`
fields when using a pre-registered snapshot — doing so returns HTTP 400.

For systemd sandboxes, wait an additional 30 seconds after `started` for
systemd to finish reaching `running` state before executing any commands.

### 6. Helper: copy a file into a sandbox via HTTP

Sandbox containers run inside the docker-in-docker `harbor.daytona-runner`
container (not visible in host `docker ps`), and `docker cp` does not work.
Serve files from the host and download from inside the sandbox:

```bash
copy_to_sandbox() {
  local SB_ID="$1"
  local FILE_NAME="$2"   # file name under /tmp/harbor-pkg
  local DEST_PATH="$3"
  sandbox_exec "$SB_ID" "curl -sf -o $DEST_PATH $PKG_URL/$FILE_NAME && ls -la $DEST_PATH" 60
}
```

The HTTP server started in Section 2 (port 38777) serves all needed files.

### 7. Helper: run a command inside a sandbox

```bash
sandbox_exec() {
  local SB_ID="$1"
  local CMD="$2"
  local TIMEOUT="${3:-60}"
  curl -s -X POST "$API/api/toolbox/$SB_ID/toolbox/process/execute" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"command\":\"$CMD\",\"timeout\":$TIMEOUT}"
}
```

### 8. Helper: take a screenshot and save to a local PNG

```bash
screenshot() {
  local SB_ID="$1"
  local OUT="${2:-/tmp/harbor-screenshot.png}"
  local BASE="$API/api/toolbox/$SB_ID/toolbox/computeruse"
  curl -s "$BASE/screenshot" -H "$AUTH" | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
with open('$OUT', 'wb') as f:
    f.write(base64.b64decode(data['screenshot']))
print('Saved $OUT')
"
}
```

Read the resulting PNG with the Read tool to inspect UI state.

---

## Limitations

The following conditions are expected and must not be treated as test failures:

- **Docker overlay storage fails inside the sandbox.** The nested kernel does
  not support the overlay filesystem driver, so `harbor up <service>` fails.
  These tests validate install, detection, and Docker-down recovery only —
  they do not test running Harbor services.
- **libEGL / DRI3 warnings** appear in the app log on both distros. These are
  cosmetic — there is no GPU in Xvfb. They do not indicate a defect.
- **These tests complement, not replace, `tests/app-native-setup.md`.** Full
  service-level validation requires a real native Linux host.

The following are now covered by these tests (not limitations):
- Real apt/dnf Docker package installation triggered by the installer.
- `systemctl enable/start docker` and `docker.socket` service management via
  systemd running as PID 1 inside the sandbox.
- `usermod -aG docker daytona` group addition performed by `requirements.sh`
  (only when the app runs as the `daytona` user with passworded sudo — the test
  steps enforce this via `su - daytona`).
- The `refresh-required` ("Almost done") gate in the app triggered by the
  installer shell not yet having the docker group in its session (only reachable
  when the app runs as a non-root user; all launch commands in these tests use
  `su - daytona` to ensure this).
- Recovery via a fresh login shell (`su - daytona`) that picks up the new group
  membership.

## Known product bugs (do not fix — report only)

### Harbor App hangs on startup in Daytona toolbox (fix_path_env)

`harbor-app` calls `fix_path_env::fix()` at startup, which spawns
`sh -ilc "echo _SHELL_ENV_DELIMITER_; env; exit"`. In the Daytona toolbox
execution context, the interactive shell opens `/dev/tty` and blocks
indefinitely (returns HTTP 408). This prevents the app from reaching X11.

**Workaround** (applied in every app launch step below): deploy a fake
non-interactive shell at `/usr/local/bin/fakesh` in the sandbox, then set
`SHELL=/usr/local/bin/fakesh` when launching `harbor-app`. This causes
`fix_path_env` to probe the fake shell, which exits immediately.

**Not a test environment defect** — this is a Tauri/fix_path_env limitation in
headless sandbox environments. Do not patch the product.

### `refresh-required` gate requires app to run as a non-root user

The Daytona toolbox API executes all commands as `root`. When `harbor-app`
runs as root, `requirements.sh` also runs as root (no `sudo` invocation, no
`SUDO_USER`), so the `usermod -aG docker` branch that checks
`[ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]` is skipped. Root can also
access the Docker socket without group membership, so the app proceeds directly
to the main UI without showing `refresh-required`.

**Consequence:** the `refresh-required` ("Almost done") gate and the sudo
password prompt are only observable when the app runs as the non-root `daytona`
user (who has passworded sudo). **All app launch steps below use
`su - daytona -c '...'` to ensure the app runs as `daytona`, matching the
real-user install scenario.**

---

## Test 1: Ubuntu 24.04 Ready Path (Real Install)

Verifies that the Harbor App launches into the setup gate on a clean system,
runs the full install flow including real apt Docker package installation and
systemd service enablement, shows the `refresh-required` gate, and passes
after relaunching under a fresh login shell.

**Steps:**

1. Create an Ubuntu sandbox and wait for systemd to be ready:

```bash
ID=$(create_sandbox "harbor/ubuntu-24.04-sandbox:v2.0.0")
echo "Ubuntu sandbox ID: $ID"
BASE="$API/api/toolbox/$ID/toolbox/computeruse"
# Wait for systemd to reach running state (up to 60s)
for i in $(seq 1 20); do
  STATE=$(sandbox_exec "$ID" "systemctl is-system-running 2>/dev/null || true" 10 | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','').strip())")
  echo "systemd state: $STATE"
  echo "$STATE" | grep -qE '^(running|degraded)$' && break
  sleep 3
done
```

2. Confirm clean state — no harbor install, no docker:

```bash
sandbox_exec "$ID" "ls ~/.harbor 2>&1; echo exit:$?"
sandbox_exec "$ID" "ls ~/.local/bin/harbor 2>&1; echo exit:$?"
sandbox_exec "$ID" "which docker 2>&1 || echo docker-not-found"
sandbox_exec "$ID" "systemctl is-active docker 2>&1 || true"
```

Both `~/.harbor` and `~/.local/bin/harbor` must not exist. `docker` must not
be found in PATH.

3. Copy the `.deb` package and install the Harbor App:

```bash
copy_to_sandbox "$ID" "$(basename "$DEB_PATH")" "/tmp/Harbor.deb"
sandbox_exec "$ID" "sudo apt-get install -y /tmp/Harbor.deb 2>&1 | tail -5; echo INSTALL_EXIT:$?" 120
```

4. Find the installed app binary:

```bash
APP_EXE=$(sandbox_exec "$ID" "dpkg -L harbor | grep '/bin/' | head -1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','').strip())")
echo "App binary: $APP_EXE"
```

5. Start the desktop session and wait for it to be active:

```bash
curl -s -X POST "$BASE/start" -H "$AUTH"
sleep 5
while true; do
  STATUS=$(curl -s "$BASE/status" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "desktop status: $STATUS"
  [ "$STATUS" = "active" ] && break
  sleep 3
done
```

6. Apply test-environment prerequisites in the sandbox, then launch the Harbor App.

   6a. Deploy the `fakesh` wrapper. This is required to work around the
   `fix_path_env` hang (see Known product bugs above). Without it `harbor-app`
   never connects to X11:

```bash
sandbox_exec "$ID" "printf '%s\n' '#!/bin/sh' 'exit 0' > /usr/local/bin/fakesh && chmod +x /usr/local/bin/fakesh" 10
```

   6b. Download `install.sh` into the sandbox, then launch the Harbor App as
   the `daytona` user. `HARBOR_APP_INSTALL_SCRIPT` must be a local filesystem
   path — setup.rs runs `bash <path>` and treats the value as a filename, not a
   URL. `HARBOR_REQUIREMENTS_URL` is a URL (install.sh itself curls it).
   `SHELL=/usr/local/bin/fakesh` prevents the `fix_path_env` hang.
   `DBUS_SESSION_BUS_ADDRESS` is required for the Tauri app to connect to the
   desktop session. **The app must run as `daytona` (not root)** so that
   `requirements.sh` uses `sudo` and `SUDO_USER` is populated, enabling the
   `usermod -aG docker` branch and the subsequent `refresh-required` gate.
   On Ubuntu 24.04 without the Docker APT repo, `requirements.sh` correctly
   falls back to installing `docker.io` from the distro repository:

```bash
sandbox_exec "$ID" "curl -sf -o /tmp/install.sh $PKG_URL/install.sh && chmod +x /tmp/install.sh && chown daytona /tmp/install.sh" 30
# Get the DBUS address from the running xfce4-session (started by the desktop toolbox)
DBUS_ADDR=$(sandbox_exec "$ID" "cat /tmp/xfce4-session-dbus-addr 2>/dev/null || grep -r DBUS_SESSION_BUS_ADDRESS /proc/$(pgrep -u daytona xfce4-session 2>/dev/null)/environ 2>/dev/null | tr '\\0' '\\n' | grep DBUS || echo 'unix:path=/run/user/1000/bus'" 10 | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','unix:path=/run/user/1000/bus').strip())")
echo "DBUS_ADDR: $DBUS_ADDR"
sandbox_exec "$ID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $APP_EXE &>/tmp/harbor-app.log 2>&1 &'" 5
sleep 10
screenshot "$ID" /tmp/ubuntu-t1-welcome.png
```

Read `/tmp/ubuntu-t1-welcome.png`. The setup gate must be visible with an
**Install Harbor** button.

7. Click the **Install Harbor** button. Identify its coordinates from the
   welcome screenshot, then:

```bash
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <X>, "y": <Y>, "button": "left"}'
```

Replace `<X>` and `<Y>` with the button coordinates from the screenshot.

8. Take screenshots every ~5 seconds to monitor install progress. The
   `installing-prerequisites` stage triggers real apt package downloads for
   docker-ce or docker.io — this is the most time-consuming stage. The app
   shows a terminal panel with live installer output. Total timeout: 10 minutes:

```bash
for i in $(seq 1 6); do
  sleep 5
  screenshot "$ID" "/tmp/ubuntu-t1-progress-$i.png"
done
# Continue at ~10s cadence until install finishes or times out
```

During the `installing-prerequisites` stage the app will prompt for the sudo
password in the installer prompt input. The daytona user has passworded sudo
(`sudo -n` fails) so the interactive prompt always appears. When the password
prompt is visible in a screenshot:

```bash
# Find the installer prompt input field coordinates, click it, then type password
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <PROMPT_X>, "y": <PROMPT_Y>, "button": "left"}'
# Type the password via the keyboard endpoint
curl -s -X POST "$BASE/keyboard/type" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"text": "daytona"}'
# Click the Send button
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <SEND_X>, "y": <SEND_Y>, "button": "left"}'
```

Continue taking screenshots at ~5s cadence after submitting the password.

At least one screenshot must show installer output in the terminal panel
containing text related to docker package download or installation.

9. The installer will finish with `refresh-required`. The app shows the
   "Almost done" gate ("Harbor was installed, but it can't fully connect to
   Docker yet."). Take a screenshot to confirm this gate:

```bash
screenshot "$ID" /tmp/ubuntu-t1-refresh-required.png
```

Verify with the Read tool that the "Almost done" heading and "Redetect"
button are visible.

10. Verify the install artifacts from the installer side. The following must
    all pass before relaunching:

```bash
sandbox_exec "$ID" "systemctl is-active docker; echo exit:$?" 10
sandbox_exec "$ID" "systemctl is-enabled docker || systemctl is-enabled docker.socket; echo exit:$?" 10
sandbox_exec "$ID" "docker compose version" 30
sandbox_exec "$ID" "id daytona | grep docker" 10
```

`systemctl is-active docker` must exit 0. The docker group must appear in
`id daytona` output. These confirm requirements.sh ran to completion.

11. The installer shell lacks the docker group in its session (this is why
    `refresh-required` appears — the group was just added). Relaunch the app
    as `daytona` under a login shell that has picked up the new docker group.
    Continue to use `SHELL=/usr/local/bin/fakesh` and `DBUS_SESSION_BUS_ADDRESS`:

```bash
sandbox_exec "$ID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$ID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $APP_EXE &>/tmp/harbor-app-relaunch.log 2>&1 &'" 5
sleep 10
screenshot "$ID" /tmp/ubuntu-t1-done.png
```

Read `/tmp/ubuntu-t1-done.png`. The main Services UI must now be visible —
setup gate must not appear. (The `daytona` user now has the `docker` group in
its session because `su -` starts a fresh login shell that re-reads group
membership from `/etc/group`.)

12. Verify Harbor from a login shell inside the sandbox:

```bash
sandbox_exec "$ID" "su - daytona -c 'harbor --version'" 30
sandbox_exec "$ID" "su - daytona -c 'harbor doctor --check'" 60
```

**Expectations:**

1. `ls ~/.harbor` and `ls ~/.local/bin/harbor` both fail before install
   (exit non-zero, output contains "No such file").

2. `docker` is absent from PATH and `systemctl is-active docker` returns
   non-zero before the install runs.

3. App package install exits 0 (`INSTALL_EXIT:0`).

4. Desktop status reaches `"active"` before launching the app.

5. The welcome screenshot (`/tmp/ubuntu-t1-welcome.png`) shows the **Install
   Harbor** button. Main Services tabs must not be visible.

6. At least one progress screenshot shows installer terminal output. At least
   one of the stage markers must be visible across all progress screenshots:
   `installing-prerequisites`, `installing-cli`, `linking-cli`, `verifying-cli`.

7. The `refresh-required` screenshot (`/tmp/ubuntu-t1-refresh-required.png`)
   shows the "Almost done" heading and a **Redetect** button.

8. After the installer: `systemctl is-active docker` exits 0, docker compose
   version exits 0, `id daytona` output contains `docker`.

9. After relaunch via `su - daytona`, the final screenshot
   (`/tmp/ubuntu-t1-done.png`) shows the main Services UI with category tabs
   (`Backend`, `Frontend`, or `Satellite` visible). The setup gate must not
   appear.

10. `su - daytona -c 'harbor --version'` stdout contains a version string.

11. `su - daytona -c 'harbor doctor --check'` exits 0.

---

## Test 2: Ubuntu 24.04 Existing Install Detection and Docker-down Recovery

Verifies that after a successful install the app skips the setup gate, and
that stopping docker via systemctl causes the correct degraded-state warning,
which recovers when docker is restarted.

**Precondition:** Test 1 must have completed successfully. Reuse the same
sandbox (`$ID`, `$APP_EXE`, `$BASE`).

**Steps:**

1. Kill the app from Test 1, then relaunch to verify the setup gate is skipped.
   Use the same `su - daytona` + `fakesh` + `DBUS_SESSION_BUS_ADDRESS` pattern:

```bash
sandbox_exec "$ID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$ID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $APP_EXE &>/tmp/harbor-app-t2a.log 2>&1 &'" 5
sleep 8
screenshot "$ID" /tmp/ubuntu-t2-already-installed.png
```

Read the screenshot. The main Services UI must appear directly — no setup gate.

2. Stop docker via systemctl and relaunch the app:

```bash
sandbox_exec "$ID" "systemctl stop docker docker.socket 2>/dev/null || true; sleep 3; echo DOCKER_STOPPED"
sandbox_exec "$ID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$ID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $APP_EXE &>/tmp/harbor-app-t2b.log 2>&1 &'" 5
sleep 8
screenshot "$ID" /tmp/ubuntu-t2-docker-down.png
```

Read the screenshot. The "Almost done" gate must be visible.

3. Start docker via systemctl (commands run as root in the toolbox, no sudo needed):

```bash
sandbox_exec "$ID" "systemctl start docker; sleep 5; systemctl is-active docker; echo DOCKER_RESTARTED" 30
```

4. Click the **Redetect** button. Identify its coordinates from
   `ubuntu-t2-docker-down.png`, then:

```bash
curl -s -X POST "$BASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <X>, "y": <Y>, "button": "left"}'
sleep 6
screenshot "$ID" /tmp/ubuntu-t2-recovered.png
```

**Expectations:**

1. The already-installed screenshot (`/tmp/ubuntu-t2-already-installed.png`)
   shows the main Services UI — category tabs visible, no setup gate.

2. The docker-down screenshot (`/tmp/ubuntu-t2-docker-down.png`) shows ALL of
   the following:
   - Heading: **"Almost done"**
   - Body message: "Harbor was installed, but it can't fully connect to Docker
     yet."
   - Red error text: "Harbor is installed but can't connect to Docker yet. Try
     logging out and back in."
   - A **"Redetect"** button.

3. `systemctl start docker` exits 0 and `systemctl is-active docker`
   returns `active`.

4. After clicking **Redetect**, the recovery screenshot
   (`/tmp/ubuntu-t2-recovered.png`) shows the main Services UI (category tabs
   visible, no setup gate).

---

## Test 3: Fedora 42 Ready Path (Real Install)

Mirrors Test 1 on Fedora 42. Steps differ only in sandbox snapshot, package
manager (`dnf`), and Harbor App package format (`.rpm`).

**Steps:**

1. Create a Fedora sandbox and wait for systemd:

```bash
FID=$(create_sandbox "harbor/fedora-42-sandbox:v2.0.0")
echo "Fedora sandbox ID: $FID"
FBASE="$API/api/toolbox/$FID/toolbox/computeruse"
for i in $(seq 1 20); do
  STATE=$(sandbox_exec "$FID" "systemctl is-system-running 2>/dev/null || true" 10 | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','').strip())")
  echo "systemd state: $STATE"
  echo "$STATE" | grep -qE '^(running|degraded)$' && break
  sleep 3
done
```

2. Confirm clean state:

```bash
sandbox_exec "$FID" "ls ~/.harbor 2>&1; echo exit:$?"
sandbox_exec "$FID" "ls ~/.local/bin/harbor 2>&1; echo exit:$?"
sandbox_exec "$FID" "which docker 2>&1 || echo docker-not-found"
sandbox_exec "$FID" "systemctl is-active docker 2>&1 || true"
```

3. Copy the `.rpm` package and install the Harbor App:

```bash
copy_to_sandbox "$FID" "$(basename "$RPM_PATH")" "/tmp/Harbor.rpm"
sandbox_exec "$FID" "sudo dnf install -y /tmp/Harbor.rpm 2>&1 | tail -5; echo INSTALL_EXIT:$?" 180
```

4. Find the installed app binary:

```bash
FAPP_EXE=$(sandbox_exec "$FID" "rpm -ql harbor | grep '/bin/' | head -1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','').strip())")
echo "App binary: $FAPP_EXE"
```

5. Start the desktop session and wait for it to be active:

```bash
curl -s -X POST "$FBASE/start" -H "$AUTH"
sleep 5
while true; do
  STATUS=$(curl -s "$FBASE/status" -H "$AUTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "desktop status: $STATUS"
  [ "$STATUS" = "active" ] && break
  sleep 3
done
```

6. Apply test-environment prerequisites, then launch the Harbor App.

   6a. Deploy the `fakesh` wrapper (same reason as Test 1 Step 6a):

```bash
sandbox_exec "$FID" "printf '%s\n' '#!/bin/sh' 'exit 0' > /usr/local/bin/fakesh && chmod +x /usr/local/bin/fakesh" 10
```

   6b. Download `install.sh` into the sandbox, then launch the Harbor App as
   the `daytona` user. Same rationale as Test 1 Step 6c — the app must run as
   `daytona` so `requirements.sh` uses `sudo` with `SUDO_USER` set:

```bash
sandbox_exec "$FID" "curl -sf -o /tmp/install.sh $PKG_URL/install.sh && chmod +x /tmp/install.sh && chown daytona /tmp/install.sh" 30
FDBUS_ADDR=$(sandbox_exec "$FID" "cat /tmp/xfce4-session-dbus-addr 2>/dev/null || grep -r DBUS_SESSION_BUS_ADDRESS /proc/$(pgrep -u daytona xfce4-session 2>/dev/null)/environ 2>/dev/null | tr '\\0' '\\n' | grep DBUS || echo 'unix:path=/run/user/1000/bus'" 10 | python3 -c "import sys,json; print(json.load(sys.stdin).get('stdout','unix:path=/run/user/1000/bus').strip())")
echo "FDBUS_ADDR: $FDBUS_ADDR"
sandbox_exec "$FID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$FDBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $FAPP_EXE &>/tmp/harbor-app.log 2>&1 &'" 5
sleep 10
screenshot "$FID" /tmp/fedora-t3-welcome.png
```

Read `/tmp/fedora-t3-welcome.png`. The setup gate must be visible.

7. Click **Install Harbor**:

```bash
curl -s -X POST "$FBASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <X>, "y": <Y>, "button": "left"}'
```

8. Take screenshots every ~5 seconds to monitor install progress. The
   `installing-prerequisites` stage runs `dnf install` for docker packages.
   Total timeout: 10 minutes:

```bash
for i in $(seq 1 6); do
  sleep 5
  screenshot "$FID" "/tmp/fedora-t3-progress-$i.png"
done
```

During the `installing-prerequisites` stage, the app will prompt for the sudo
password in the installer prompt input. When this input appears, type the
password and submit:

```bash
# After seeing the sudo password prompt in a screenshot:
# Find the installer prompt input field coordinates, click it, then type password
curl -s -X POST "$FBASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <PROMPT_X>, "y": <PROMPT_Y>, "button": "left"}'
# Type the password character by character via the keyboard endpoint
curl -s -X POST "$FBASE/keyboard/type" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"text": "daytona"}'
# Click the Send button
curl -s -X POST "$FBASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <SEND_X>, "y": <SEND_Y>, "button": "left"}'
```

Continue taking screenshots at ~5s cadence after submitting the password.

9. After the installer finishes, take a screenshot of the `refresh-required`
   gate:

```bash
screenshot "$FID" /tmp/fedora-t3-refresh-required.png
```

10. Verify install artifacts:

```bash
sandbox_exec "$FID" "systemctl is-active docker; echo exit:$?" 10
sandbox_exec "$FID" "systemctl is-enabled docker || systemctl is-enabled docker.socket; echo exit:$?" 10
sandbox_exec "$FID" "docker compose version" 30
sandbox_exec "$FID" "id daytona | grep docker" 10
```

11. Relaunch as `daytona` under a fresh login shell to pick up the docker group.
    Continue to use `SHELL=/usr/local/bin/fakesh` and `DBUS_SESSION_BUS_ADDRESS`:

```bash
sandbox_exec "$FID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$FID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$FDBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $FAPP_EXE &>/tmp/harbor-app-relaunch.log 2>&1 &'" 5
sleep 10
screenshot "$FID" /tmp/fedora-t3-done.png
```

12. Verify Harbor from a login shell:

```bash
sandbox_exec "$FID" "su - daytona -c 'harbor --version'" 30
sandbox_exec "$FID" "su - daytona -c 'harbor doctor --check'" 60
```

**Expectations:**

1. `ls ~/.harbor` and `ls ~/.local/bin/harbor` both fail before install.

2. `docker` is absent from PATH and `systemctl is-active docker` returns
   non-zero before the install runs.

3. App package install exits 0 (`INSTALL_EXIT:0`).

4. Desktop status reaches `"active"` before launching the app.

5. The welcome screenshot (`/tmp/fedora-t3-welcome.png`) shows **Install
   Harbor** button; main Services tabs must not be visible.

6. At least one progress screenshot shows installer terminal output with
   stage markers: `installing-prerequisites`, `installing-cli`, `linking-cli`,
   or `verifying-cli`.

7. The sudo password prompt appears during `installing-prerequisites`. After
   typing `daytona` and clicking Send, install continues without error.

8. The `refresh-required` screenshot (`/tmp/fedora-t3-refresh-required.png`)
   shows the "Almost done" heading and **Redetect** button.

9. After the installer: `systemctl is-active docker` exits 0, docker compose
   version exits 0, `id daytona` output contains `docker`.

10. After relaunch via `su - daytona`, the final screenshot
    (`/tmp/fedora-t3-done.png`) shows the main Services UI with category tabs
    visible. The setup gate must not appear.

11. `su - daytona -c 'harbor --version'` stdout contains a version string.

12. `su - daytona -c 'harbor doctor --check'` exits 0.

---

## Test 4: Fedora 42 Existing Install Detection and Docker-down Recovery

Mirrors Test 2 on Fedora 42.

**Precondition:** Test 3 must have completed successfully. Reuse the same
sandbox (`$FID`, `$FAPP_EXE`, `$FBASE`).

**Steps:**

1. Kill the app and relaunch to verify the setup gate is skipped.
   Use the same `su - daytona` + `fakesh` + `DBUS_SESSION_BUS_ADDRESS` pattern:

```bash
sandbox_exec "$FID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$FID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$FDBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $FAPP_EXE &>/tmp/harbor-app-t4a.log 2>&1 &'" 5
sleep 8
screenshot "$FID" /tmp/fedora-t4-already-installed.png
```

Read the screenshot. The main Services UI must appear directly — no setup gate.

2. Stop docker via systemctl and relaunch the app:

```bash
sandbox_exec "$FID" "systemctl stop docker docker.socket 2>/dev/null || true; sleep 3; echo DOCKER_STOPPED"
sandbox_exec "$FID" "pkill -f harbor-app || true; sleep 2"
sandbox_exec "$FID" "su - daytona -c 'DISPLAY=:0 SHELL=/usr/local/bin/fakesh DBUS_SESSION_BUS_ADDRESS=$FDBUS_ADDR HARBOR_APP_INSTALL_SCRIPT=/tmp/install.sh HARBOR_REQUIREMENTS_URL=$PKG_URL/requirements.sh nohup $FAPP_EXE &>/tmp/harbor-app-t4b.log 2>&1 &'" 5
sleep 8
screenshot "$FID" /tmp/fedora-t4-docker-down.png
```

3. Start docker via systemctl (commands run as root in the toolbox, no sudo needed):

```bash
sandbox_exec "$FID" "systemctl start docker; sleep 5; systemctl is-active docker; echo DOCKER_RESTARTED" 30
```

4. Click **Redetect** and take a recovery screenshot:

```bash
curl -s -X POST "$FBASE/mouse/click" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"x": <X>, "y": <Y>, "button": "left"}'
sleep 6
screenshot "$FID" /tmp/fedora-t4-recovered.png
```

**Expectations:**

1. The already-installed screenshot (`/tmp/fedora-t4-already-installed.png`)
   shows the main Services UI directly — category tabs visible, no setup gate.

2. The docker-down screenshot (`/tmp/fedora-t4-docker-down.png`) shows ALL of:
   - Heading: **"Almost done"**
   - Body: "Harbor was installed, but it can't fully connect to Docker yet."
   - Red error: "Harbor is installed but can't connect to Docker yet. Try
     logging out and back in."
   - A **"Redetect"** button.

3. `systemctl start docker` exits 0 and `systemctl is-active docker`
   returns `active`.

4. After clicking **Redetect**, the recovery screenshot
   (`/tmp/fedora-t4-recovered.png`) shows the main Services UI with category
   tabs visible and no setup gate.

---

## Cleanup

Delete both sandboxes after all tests complete. Keep the snapshots — they are
reused across test runs.

```bash
# Delete Ubuntu sandbox
curl -s -X DELETE "$API/api/sandbox/$ID" -H "$AUTH"
echo "Ubuntu sandbox deleted: $ID"

# Delete Fedora sandbox
curl -s -X DELETE "$API/api/sandbox/$FID" -H "$AUTH"
echo "Fedora sandbox deleted: $FID"

# Stop the host package server
pkill -f "http.server 38777" || true

# Stop the host watchdog
kill $(cat /tmp/host-watchdog.pid 2>/dev/null) 2>/dev/null || pkill -f host-watchdog.sh || true

# Verify both are gone
curl -s "$API/api/sandbox" -H "$AUTH" | python3 -c "
import sys, json
sandboxes = json.load(sys.stdin)['items']
ids = [s['id'] for s in sandboxes]
print('Remaining sandboxes:', ids)
"
```

To verify snapshots are still registered:

```bash
curl -s "$API/api/snapshots" -H "$AUTH" | python3 -c "
import sys, json
snaps = json.load(sys.stdin)['items']
for s in snaps:
    print(s['name'], '->', s.get('state','?'))
"
```
