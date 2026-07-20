# Harbor Tests

Container-based test runner. One command runs every suite against every
supported distro row. Works on any host with docker (or podman as fallback).

```bash
harbor dev test                                 # everything, parallel
harbor dev test --suite smoke                   # one suite, every row
harbor dev test --suite launch-smoke            # launch adapter smoke tests
harbor dev test --suite boost-agentic-smoke     # Boost agentic module pytest battery
harbor dev test --distros ubuntu-2404           # every suite, one row
harbor dev test --distros ubuntu-2404 --suite install,smoke
harbor dev test --keep                          # leave containers running
harbor dev test --rebuild                       # force image rebuild
harbor dev test --install-source github         # curl the release installer
harbor dev test --runtime podman                # override autodetect
harbor dev test --jobs 1                        # serial
harbor dev test --json                          # machine-readable
```

Exit code is `0` iff every `(row, suite)` pair passed.

## Layout

```
tests/
├── run.ts             # orchestrator (Deno)
├── containers/        # one Containerfile per distro row
├── suites/            # one bash script per logical check
├── fixtures/          # services the suites depend on (mock-openai, …)
├── http/              # httpYac request batteries
├── lib/               # bash helpers shared by suites
├── artifacts/         # per-run logs, gitignored
└── README.md
```

## Primitives

- **Suite** — a bash script under `suites/`. Self-contained: assumes
  `harbor` is on `PATH` (install has run), takes no arguments, exits `0`
  on pass. Prints one `[<suite>] <step>` line per logical step. Cleans
  up its own state on exit via `trap`. Suites run in filename order, so
  `01-install.sh` reliably precedes `02-cli.sh`, `03-smoke.sh`,
  `04-integration.sh`, `05-launch-smoke.sh`, and `06-boost-agentic-smoke.sh`.
  When `--suite` selects a suite that assumes an installed harbor (every
  suite except `install` and the self-bootstrapping `boost-agentic-smoke`)
  without also selecting `install`, the orchestrator auto-prepends the
  install suite — `--suite cli` runs `install,cli`.
- **Row** — a Containerfile under `containers/`. Each row image boots
  systemd as PID 1, runs dockerd nested inside, and has curl + git + jq +
  httpYac pre-installed.
- **Orchestrator** — `run.ts`. Probes the host, materializes a bounded
  git-tracked repo artifact once per run (`tests/stage-repo.ts` via
  `git ls-files` — untracked/gitignored local blobs never enter the matrix),
  builds row images, launches privileged systemd containers, mounts the
  artifact read-only at `/opt/harbor-test/repo`, waits for the nested
  dockerd, execs each suite, captures output to both tty and a logfile,
  tears down. Reports a results matrix. The host working tree is never
  bind-mounted into rows.

## Adding a row

One file. Copy an existing Containerfile (e.g. `ubuntu-2404.Containerfile`)
and adjust the base image and package names. The orchestrator discovers
rows by filename, so no registration is needed.

Each row is expected to consume the shared `harbor-test/base` image via a
first-stage `FROM harbor-test/base AS harbor-base` and then
`COPY --from=harbor-base /daemon.json /etc/docker/daemon.json`. The
orchestrator builds `base.Containerfile` once, before any row, so the
reference resolves locally without a registry. Keeping the fuse-overlayfs
daemon.json in a single file prevents per-distro drift. `base` itself is
excluded from the matrix by name.

Four invariants every row must uphold:

1. systemd PID 1 — `CMD ["/sbin/init"]` (Alpine uses OpenRC's `/sbin/init`).
2. `/etc/docker/daemon.json` pins the nested daemon to `fuse-overlayfs`.
3. `/opt/harbor-test/repo` and `/opt/harbor-test/artifacts` exist as
   empty directories (orchestrator bind-mounts into them). Do **not**
   stage under `/mnt` or `/tmp` — systemd inside the container shadows
   those with tmpfs at boot, silently voiding the mounts.
4. docker is enabled at boot (`systemctl enable docker` or
   `rc-update add docker default`). Saves a roundtrip at run time.

## Adding a suite

One file under `suites/`. Name it `NN-<name>.sh` so its order is obvious.
The suite contract:

- Exits `0` on pass.
- Prints one `[<name>] <step>` line per step — the orchestrator prefixes
  it again with `[<row>:<name>]` so output stays readable under parallel
  execution.
- Cleans up its own state even on failure (`trap ... EXIT`).
- Drops any extra artefacts under `/opt/harbor-test/artifacts/<name>/`
  inside the container; they appear on the host at
  `tests/artifacts/<run-id>/<row>/<name>/` automatically via the bind
  mount — no copy step.
- Every wait has a bounded timeout.

### Boost agentic smoke (`06-boost-agentic-smoke.sh`)

Runs the Boost agentic pytest battery against the Harbor Boost image built
inside the row's nested docker daemon. Tests are bind-mounted from the staged
repo; pytest is invoked with `uv run --with pytest --with pytest-asyncio` inside
the Boost image so the battery matches production dependencies without baking
test tools into the service image.

```bash
harbor dev test --suite boost-agentic-smoke   # defaults to fedora-43, --jobs 1
HARBOR_TEST_AGENTIC_MODE=host bash tests/suites/06-boost-agentic-smoke.sh
```

The orchestrator materializes a git-tracked repo artifact once per run
(`git ls-files` — local gitignored blobs never enter rows). Regression:
`deno test --allow-read --allow-write --allow-run tests/run-stage.test.ts`.

Shared helpers live in `tests/lib/boost-agentic.sh`.

## Services integration runner

`tests/services-integration.sh` is a separate, host-run soak that starts real
Harbor services on the host docker (not the container matrix above) and
verifies each one works — startup, health endpoints, and an actual LLM
round-trip where applicable. It automates the spec in
`tests/services-integration.md`, which documents every check and the
prerequisites (CPU-friendly GGUF model in the HF cache, host-installed
`hermes`/`opencode` for Group C — both auto-skipped when absent).

```bash
./tests/services-integration.sh                 # all CPU-safe groups (A B C D F G H)
./tests/services-integration.sh --groups B,G    # selected groups only
./tests/services-integration.sh --list          # list groups and checks
```

Groups run serially (services share ports/GPU) and each group ends with
`harbor down`, even on failure. Group E (comfyui) is opt-in via `--groups E`.
Prints one PASS/FAIL line per check plus a summary; exits non-zero on any FAIL.

## Artifacts

Each run gets `tests/artifacts/<run-id>/<row>/`, where `<run-id>` is
`YYYYMMDD-HHMMSS-<sha8>`. For each suite the orchestrator captures:

- `tests/artifacts/<run-id>/<row>/<suite>.log` — live stdout+stderr.
- `tests/artifacts/<run-id>/<row>/<suite>/` — optional suite-dropped files.

The entire directory is gitignored.

## Container-as-VM: why privileged

Every row runs `--privileged --cgroupns=host` with `/sys/fs/cgroup` bind
mounted read-write. That is what lets systemd come up as PID 1 and start
a nested dockerd. The orchestrator refuses to run against rootless
docker (which cannot grant `--privileged`) and asks the user to either
use rootful docker or rerun with `--runtime podman`. Rootless podman
supports this combination natively.

On SELinux-enforcing hosts, bind mounts get `:z` relabelled and docker
gets `--security-opt label=disable` to unblock the inner daemon. Both
are auto-detected — no user knob.

## CI

GitHub Actions runs `harbor dev test --json` on a nightly schedule and on
PRs touching `harbor.sh`, `install.sh`, `requirements.sh`, or `tests/`.
Same command path on every machine.
