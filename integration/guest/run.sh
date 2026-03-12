#!/usr/bin/env bash
# Harbor integration test runner (guest-side).
# Must be called with --inside-vm flag.
set -euo pipefail

HARBOR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARBOR_INT_RUN_ID="$(date +%Y%m%d-%H%M%S)"
HARBOR_INT_ARTIFACTS_DIR="${HARBOR_ROOT}/integration/artifacts/${HARBOR_INT_RUN_ID}"
HARBOR_INT_VERBOSE=0
HARBOR_INT_INSIDE_VM=0
SUITE_START=$(date +%s)
_TEARDOWN_DONE=0

export HARBOR_ROOT HARBOR_INT_RUN_ID HARBOR_INT_ARTIFACTS_DIR
export HARBOR_INT_TEST_STATUS="fail"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --inside-vm)
      HARBOR_INT_INSIDE_VM=1
      shift
      ;;
    --artifacts-dir)
      HARBOR_INT_ARTIFACTS_DIR="$2"
      export HARBOR_INT_ARTIFACTS_DIR
      shift 2
      ;;
    --verbose)
      HARBOR_INT_VERBOSE=1
      shift
      ;;
    *)
      echo "[run] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Safety guard — must be inside a VM/CI environment
# ---------------------------------------------------------------------------
if [[ "$HARBOR_INT_INSIDE_VM" -ne 1 ]]; then
  echo "[run] ERROR: This script must be run with --inside-vm flag." >&2
  echo "[run]        It is intended to run inside a VM or CI environment only." >&2
  echo "[run]        Pass --inside-vm explicitly to confirm this is intentional." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step tracking arrays
# ---------------------------------------------------------------------------
declare -a _STEP_NAMES=()
declare -a _STEP_STATUS=()
declare -a _STEP_ELAPSED=()
declare -a _STEP_ERRORS=()
declare -a _PHASE_NAMES=()
declare -a _PHASE_STATUS=()
declare -a _PHASE_ELAPSED=()
_SUITE_FAILED=0
_ACTIVE_PHASE=""
_ACTIVE_PHASE_START=0
_ARTIFACT_COLLECTION_DONE=0

log() { echo "[run] $*"; }

_phase_begin() {
  local name="$1"

  if [[ -n "$_ACTIVE_PHASE" ]]; then
    _phase_end "PASS"
  fi

  _ACTIVE_PHASE="$name"
  _ACTIVE_PHASE_START=$(date +%s)
  log "=== Phase: ${name} ==="
}

_phase_end() {
  local status="${1:-PASS}"

  if [[ -z "$_ACTIVE_PHASE" ]]; then
    return 0
  fi

  local end elapsed
  end=$(date +%s)
  elapsed=$(( end - _ACTIVE_PHASE_START ))

  _PHASE_NAMES+=("$_ACTIVE_PHASE")
  _PHASE_STATUS+=("$status")
  _PHASE_ELAPSED+=("${elapsed}s")
  log "=== Phase complete: ${_ACTIVE_PHASE} — ${status} (${elapsed}s) ==="

  _ACTIVE_PHASE=""
  _ACTIVE_PHASE_START=0
}

# ---------------------------------------------------------------------------
# run_step: Execute one test step with timing, streaming output, pass/fail tracking
# Usage: run_step "Step name" cmd [args...]
# ---------------------------------------------------------------------------
run_step() {
  local name="$1"; shift
  local stepnum=$(( ${#_STEP_NAMES[@]} + 1 ))
  local label="${stepnum}. ${name}"
  local start end elapsed
  start=$(date +%s)
  local tmpfile
  tmpfile=$(mktemp)

  log "┌─ ${label}"

  # set +e so a failing command does not trigger bash errexit through the pipe
  set +e
  "$@" 2>&1 | tee "$tmpfile"
  local ret="${PIPESTATUS[0]}"
  set -e

  end=$(date +%s)
  elapsed=$(( end - start ))

  _STEP_NAMES+=("$label")
  _STEP_ELAPSED+=("${elapsed}s")

  if [[ "$ret" -eq 0 ]]; then
    _STEP_STATUS+=("PASS")
    _STEP_ERRORS+=("")
    log "└─ ${label} — PASS (${elapsed}s)"
  else
    _STEP_STATUS+=("FAIL")
    local snippet
    snippet=$(tail -3 "$tmpfile" | sed 's/^/    /')
    _STEP_ERRORS+=("exit code ${ret}:"$'\n'"${snippet}")
    log "└─ ${label} — FAIL (${elapsed}s, exit=${ret})"
    _SUITE_FAILED=1
  fi

  rm -f "$tmpfile"
}

# ---------------------------------------------------------------------------
# print_summary: Print a formatted table of step results
# ---------------------------------------------------------------------------
print_summary() {
  local i total_elapsed
  total_elapsed=$(( $(date +%s) - SUITE_START ))

  # Column content widths (display characters)
  local name_w=40  # minimum width for step name column content
  local stat_w=6   # "✓ PASS" / "✗ FAIL" are 6 display chars each
  local time_w=8   # enough for "9999s   "

  # Expand name column to fit the longest recorded step name
  for (( i=0; i<${#_STEP_NAMES[@]}; i++ )); do
    if [[ "${#_STEP_NAMES[$i]}" -gt "$name_w" ]]; then
      name_w="${#_STEP_NAMES[$i]}"
    fi
  done
  # Ensure "Overall" fits (7 chars)
  if [[ 7 -gt "$name_w" ]]; then
    name_w=7
  fi

  # Build separator (col width = content + 2 spaces padding)
  local sep_name sep_stat sep_time sep
  printf -v sep_name '%*s' $(( name_w + 2 )) ''
  sep_name="${sep_name// /-}"
  printf -v sep_stat '%*s' $(( stat_w + 2 )) ''
  sep_stat="${sep_stat// /-}"
  printf -v sep_time '%*s' $(( time_w + 2 )) ''
  sep_time="${sep_time// /-}"
  sep="+${sep_name}+${sep_stat}+${sep_time}+"

  echo ""
  echo "$sep"
  printf "| %-*s | %-*s | %-*s |\n" \
    "$name_w" "Step" \
    "$stat_w" "Status" \
    "$time_w" "Time"
  echo "$sep"

  for (( i=0; i<${#_STEP_NAMES[@]}; i++ )); do
    local sname="${_STEP_NAMES[$i]}"
    local sstat="${_STEP_STATUS[$i]}"
    local stime="${_STEP_ELAPSED[$i]}"
    local status_icon
    if [[ "$sstat" == "PASS" ]]; then
      status_icon="✓ PASS"
    else
      status_icon="✗ FAIL"
    fi
    # printf for ASCII columns; status_icon printed verbatim (Unicode-safe bypass)
    local row_name row_time
    printf -v row_name "%-*s" "$name_w" "$sname"
    printf -v row_time "%-*s" "$time_w" "$stime"
    echo "| $row_name | $status_icon | $row_time |"
  done

  echo "$sep"

  # Overall summary row
  local overall_stat
  if [[ "$_SUITE_FAILED" -eq 0 ]]; then
    overall_stat="PASS"
  else
    overall_stat="FAIL"
  fi
  local row_overall row_time_total
  printf -v row_overall    "%-*s" "$name_w" "Overall"
  printf -v row_time_total "%-*s" "$time_w" "${total_elapsed}s"
  printf "| %s | %-*s | %s |\n" "$row_overall" "$stat_w" "$overall_stat" "$row_time_total"
  echo "$sep"

  # Error details section
  local had_errors=0
  for (( i=0; i<${#_STEP_NAMES[@]}; i++ )); do
    if [[ "${_STEP_STATUS[$i]}" == "FAIL" ]]; then
      had_errors=1
      break
    fi
  done

  if [[ "$had_errors" -eq 1 ]]; then
    echo ""
    echo "ERRORS:"
    for (( i=0; i<${#_STEP_NAMES[@]}; i++ )); do
      if [[ "${_STEP_STATUS[$i]}" == "FAIL" ]]; then
        echo "  [${_STEP_NAMES[$i]}]"
        while IFS= read -r line; do
          echo "    $line"
        done <<< "${_STEP_ERRORS[$i]}"
      fi
    done
  fi

  echo ""
}

print_phase_summary() {
  local i
  local name_w=34
  local stat_w=6
  local time_w=8

  for (( i=0; i<${#_PHASE_NAMES[@]}; i++ )); do
    if [[ "${#_PHASE_NAMES[$i]}" -gt "$name_w" ]]; then
      name_w="${#_PHASE_NAMES[$i]}"
    fi
  done
  if [[ 7 -gt "$name_w" ]]; then
    name_w=7
  fi

  local sep_name sep_stat sep_time sep
  printf -v sep_name '%*s' $(( name_w + 2 )) ''
  sep_name="${sep_name// /-}"
  printf -v sep_stat '%*s' $(( stat_w + 2 )) ''
  sep_stat="${sep_stat// /-}"
  printf -v sep_time '%*s' $(( time_w + 2 )) ''
  sep_time="${sep_time// /-}"
  sep="+${sep_name}+${sep_stat}+${sep_time}+"

  echo ""
  echo "PHASE SUMMARY:"
  echo "$sep"
  printf "| %-*s | %-*s | %-*s |\n" \
    "$name_w" "Phase" \
    "$stat_w" "Status" \
    "$time_w" "Time"
  echo "$sep"

  for (( i=0; i<${#_PHASE_NAMES[@]}; i++ )); do
    local pname="${_PHASE_NAMES[$i]}"
    local pstat="${_PHASE_STATUS[$i]}"
    local ptime="${_PHASE_ELAPSED[$i]}"
    local status_icon
    if [[ "$pstat" == "PASS" ]]; then
      status_icon="✓ PASS"
    else
      status_icon="✗ FAIL"
    fi
    local row_name row_time
    printf -v row_name "%-*s" "$name_w" "$pname"
    printf -v row_time "%-*s" "$time_w" "$ptime"
    echo "| $row_name | $status_icon | $row_time |"
  done

  echo "$sep"
}

# ---------------------------------------------------------------------------
# _on_exit: Always runs on EXIT — teardown, summary, artifact collection
# ---------------------------------------------------------------------------
_on_exit() {
  set +e
  local _log_dir="${HARBOR_INT_ARTIFACTS_DIR}/container-logs"
  mkdir -p "$_log_dir"

  if [[ -n "$_ACTIVE_PHASE" && "$_ACTIVE_PHASE" != "Teardown/artifact collection" ]]; then
    if [[ "$_SUITE_FAILED" -eq 0 ]]; then
      _phase_end "PASS"
    else
      _phase_end "FAIL"
    fi
  fi

  if [[ -z "$_ACTIVE_PHASE" ]]; then
    _phase_begin "Teardown/artifact collection"
  fi

  # Fallback teardown — only runs on crash/abort when _teardown never completed.
  # Captures logs here (before harbor down) so they are never lost.
  # In the normal success flow _teardown already captured logs and set _TEARDOWN_DONE=1,
  # so this block is skipped and the captured file is preserved.
  if (( _TEARDOWN_DONE == 0 )); then
    docker logs harbor.mock-openai > "$_log_dir/harbor.mock-openai.txt" 2>&1 || true
    log "Tearing down (exit handler)..."
    if ! _run_harbor_down; then
      _SUITE_FAILED=1
    fi
    _TEARDOWN_DONE=1
  fi

  if (( _ARTIFACT_COLLECTION_DONE == 0 )); then
    bash "${HARBOR_ROOT}/integration/guest/collect-artifacts.sh" || true
    _ARTIFACT_COLLECTION_DONE=1
  fi

  if [[ -n "$_ACTIVE_PHASE" ]]; then
    if [[ "$_SUITE_FAILED" -eq 0 ]]; then
      _phase_end "PASS"
    else
      _phase_end "FAIL"
    fi
  fi

  print_phase_summary
  print_summary
}
trap _on_exit EXIT

# ---------------------------------------------------------------------------
# Source readiness helpers (or define inline fallback)
# ---------------------------------------------------------------------------
READINESS_LIB="${HARBOR_ROOT}/integration/lib/readiness.sh"
if [[ -f "$READINESS_LIB" ]]; then
  # shellcheck source=../lib/readiness.sh
  source "$READINESS_LIB"
else
  log "WARNING: readiness library not found — defining inline fallback"
  wait_for_http() {
    local url="$1"
    local timeout="${2:-60}"
    local interval=3
    local elapsed=0
    log "Waiting for $url (timeout: ${timeout}s)"
    until curl -sf "$url" > /dev/null 2>&1; do
      if [[ $elapsed -ge $timeout ]]; then
        log "ERROR: Timed out waiting for $url"
        return 1
      fi
      sleep "$interval"
      elapsed=$(( elapsed + interval ))
    done
    log "  $url is ready (${elapsed}s)"
  }
fi

# ---------------------------------------------------------------------------
# Helper functions — must be defined before run_step calls
# ---------------------------------------------------------------------------
_bootstrap() {
  log "Running requirements.sh"
  bash "${HARBOR_ROOT}/requirements.sh"
  if ! command -v node > /dev/null 2>&1; then
    log "Node.js not found — installing via apt-get"
    sudo apt-get install -y nodejs npm
  fi
  log "node version: $(node --version 2>/dev/null || echo 'not found')"
  log "npm version:  $(npm --version 2>/dev/null || echo 'not found')"
  if ! command -v httpyac > /dev/null 2>&1; then
    log "Installing httpyac..."
    sudo npm install -g httpyac 2>&1 | tail -3
  else
    log "httpyac: $(httpyac --version 2>/dev/null || echo 'unknown')"
  fi
}

_wait_ready() {
  local port="${HARBOR_MOCK_OPENAI_HOST_PORT:-29350}"
  wait_for_http "http://localhost:${port}/health" 60
}

_harbor_down_logged_failure() {
  local output_file="$1"

  sed -E 's/\x1B\[[0-9;]*[[:alpha:]]//g' "$output_file" | grep -Eq '\[ERROR\].*Failed to stop services \(exit code: [0-9]+\)'
}

_run_harbor_down() {
  local output_file
  local down_status
  local errexit_was_on=0

  output_file=$(mktemp)
  if [[ $- == *e* ]]; then
    errexit_was_on=1
  fi

  set +e
  bash "${HARBOR_ROOT}/harbor.sh" down mock-openai 2>&1 | tee "$output_file"
  down_status="${PIPESTATUS[0]}"
  if [[ "$errexit_was_on" -eq 1 ]]; then
    set -e
  fi

  # Harbor can log an explicit teardown error while still exiting 0.
  if [[ "$down_status" -eq 0 ]] && _harbor_down_logged_failure "$output_file"; then
    down_status=1
  fi

  rm -f "$output_file"
  return "$down_status"
}

_http_tests() {
  local http_file="${HARBOR_ROOT}/integration/http/smoke.http"
  if [[ ! -f "$http_file" ]]; then
    echo "[run] ERROR: HTTP test file not found: $http_file" >&2
    return 1
  fi
  # Run from /tmp so httpyac has no git root to scan from (avoids EIO/ENOTDIR
  # errors on stale named pipes and build artifacts in the workspace)
  local tmp_dir
  tmp_dir=$(mktemp -d)
  cp "$http_file" "$tmp_dir/"
  (cd "$tmp_dir" && httpyac send "$(basename "$http_file")" --all --output short)
  local exit_code=$?
  rm -rf "$tmp_dir"
  return $exit_code
}

_teardown() {
  # Capture container logs before docker compose down removes them
  local _log_dir="${HARBOR_INT_ARTIFACTS_DIR}/container-logs"
  mkdir -p "$_log_dir" 2>/dev/null || true
  docker logs harbor.mock-openai > "$_log_dir/harbor.mock-openai.txt" 2>&1 || true
  log "Captured mock-openai logs ($(wc -l < "$_log_dir/harbor.mock-openai.txt" 2>/dev/null || echo 0) lines)"

  local teardown_status=0
  _run_harbor_down || teardown_status=$?
  _TEARDOWN_DONE=1
  return "$teardown_status"
}

# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------
cd "$HARBOR_ROOT"

_phase_begin "Bootstrap/setup"

# STEP 1: Preflight
run_step "Preflight" bash "${HARBOR_ROOT}/integration/guest/preflight.sh"

# STEP 2: Install dependencies
run_step "Install dependencies" _bootstrap

# Docker group refresh — AFTER bootstrap, BEFORE Harbor commands.
# If docker info fails but works under sg docker, re-exec the whole script
# under the docker group so subsequent Harbor commands have group access.
if ! docker info > /dev/null 2>&1; then
  if sg docker -c "docker info" > /dev/null 2>&1; then
    log "Docker group membership stale — re-executing under docker group..."
    _extra=("--inside-vm" "--artifacts-dir" "${HARBOR_INT_ARTIFACTS_DIR}")
    [[ "$HARBOR_INT_VERBOSE" -eq 1 ]] && _extra+=("--verbose")
    trap - EXIT
    exec sg docker -c "bash '${BASH_SOURCE[0]}' $(printf '%q ' "${_extra[@]}")"
  else
    echo "[run] ERROR: Cannot access Docker even with docker group." >&2
    exit 1
  fi
fi

# STEP 3: Harbor config update (unconditional — ensures .env is always current)
run_step "Harbor config update" bash "${HARBOR_ROOT}/harbor.sh" config update

if [[ "$_SUITE_FAILED" -eq 0 ]]; then
  _phase_end "PASS"
else
  _phase_end "FAIL"
fi

_phase_begin "Harbor startup and readiness"

# STEP 4: Start mock-openai ONLY — --no-defaults suppresses ollama+webui defaults
run_step "Start mock-openai" bash "${HARBOR_ROOT}/harbor.sh" up --no-defaults mock-openai

# STEP 5: Wait for service to be healthy
run_step "Service readiness" _wait_ready

# STEP 6: harbor ls (verify CLI produces output cleanly)
run_step "harbor ls" bash "${HARBOR_ROOT}/harbor.sh" ls

# STEP 7: harbor ps mock-openai (scoped to just our service — avoids override.env noise)
run_step "harbor ps mock-openai" bash "${HARBOR_ROOT}/harbor.sh" ps mock-openai

if [[ "$_SUITE_FAILED" -eq 0 ]]; then
  _phase_end "PASS"
else
  _phase_end "FAIL"
fi

_phase_begin "Smoke validation"

# STEP 8: HTTP smoke tests via httpYac
run_step "HTTP smoke tests" _http_tests

if [[ "$_SUITE_FAILED" -eq 0 ]]; then
  _phase_end "PASS"
else
  _phase_end "FAIL"
fi

_phase_begin "Teardown/artifact collection"

# STEP 9: Teardown
run_step "Teardown" _teardown
_TEARDOWN_DONE=1

# Set final status — only "pass" when every step passed
if [[ "$_SUITE_FAILED" -eq 0 ]]; then
  export HARBOR_INT_TEST_STATUS="pass"
fi

# exit fires _on_exit trap: prints summary and collects artifacts
exit "$_SUITE_FAILED"
