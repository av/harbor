#!/usr/bin/env bash
# Shared helpers for Boost agentic pytest batteries.
#
# Modes:
#   container — run pytest in a one-off container from the Harbor Boost image
#   host        — run pytest from the working tree via uv (dev/CI shortcut)

boost_agentic_test_targets() {
  cat <<'EOF'
tests/test_agentic_infra.py
tests/test_agentic_integration.py
tests/test_agentic_edge_cases.py
tests/test_agentic_workflow_chains.py
tests/test_shipyard_workflow.py
tests/test_workflows.py
tests/test_caveman.py
tests/test_keel.py
tests/test_ponytail.py
tests/test_autocheck.py
tests/test_sightline.py
tests/test_diffscope.py
tests/test_diffscope_git_merge.py
tests/test_orchestrate.py
EOF
}

# Usage: discover_boost_image
# Prints the repository:tag for the most recently built Boost service image.
discover_boost_image() {
  local img=""

  img=$(docker images \
    --filter "label=com.docker.compose.service=boost" \
    --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | head -1 || true)
  if [[ -n "$img" && "$img" != "<none>:<none>" ]]; then
    printf '%s\n' "$img"
    return 0
  fi

  img=$(docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E '(^|[-/])boost:' \
    | grep -v '<none>' \
    | head -1 || true)
  if [[ -n "$img" ]]; then
    printf '%s\n' "$img"
    return 0
  fi

  return 1
}

# Usage: run_boost_agentic_pytest <mode> <boost_dir> [boost_image]
# Exits non-zero when pytest fails or prerequisites are missing.
run_boost_agentic_pytest() {
  local mode="$1"
  local boost_dir="$2"
  local boost_image="${3:-}"
  local -a targets=()
  local target

  if [[ ! -d "$boost_dir/tests" ]]; then
    echo "[boost-agentic] ERROR: missing tests under ${boost_dir}" >&2
    return 1
  fi

  while IFS= read -r target; do
    [[ -n "$target" ]] && targets+=("$target")
  done < <(boost_agentic_test_targets)

  case "$mode" in
    host)
      if ! command -v uv >/dev/null 2>&1; then
        echo "[boost-agentic] ERROR: uv not found on PATH (required for host mode)" >&2
        return 1
      fi
      (
        cd "$boost_dir"
        default_venv="${boost_dir}/.venv"
        # Container builds can leave a root-owned .venv on the bind mount; fall
        # back to a disposable env under /tmp when the project venv is not usable.
        if [[ -e "$default_venv" ]] && [[ ! -w "$default_venv" ]]; then
          export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/harbor-boost-agentic-venv"
        fi
        UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
          uv run --with pytest --with pytest-asyncio \
          pytest -q "${targets[@]}"
      )
      ;;
    container)
      if [[ -z "$boost_image" ]]; then
        boost_image="$(discover_boost_image)" || {
          echo "[boost-agentic] ERROR: could not discover Boost image (run 'harbor build boost' first)" >&2
          return 1
        }
      fi
      # Mount only sources + lockfiles so uv's ephemeral .venv stays inside the
      # container and does not clobber a developer's host .venv bind mount.
      docker run --rm \
        -e UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
        -v "${boost_dir}/tests:/boost/tests:ro" \
        -v "${boost_dir}/src:/boost/src:ro" \
        -v "${boost_dir}/pyproject.toml:/boost/pyproject.toml:ro" \
        -v "${boost_dir}/uv.lock:/boost/uv.lock:ro" \
        -w /boost \
        "$boost_image" \
        uv run --with pytest --with pytest-asyncio \
        pytest -q "${targets[@]}"
      ;;
    *)
      echo "[boost-agentic] ERROR: unknown mode '${mode}' (expected container or host)" >&2
      return 1
      ;;
  esac
}