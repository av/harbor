#!/usr/bin/env bash
# Harbor Launch Showcase Demo
#
# A focused tmux demo of `harbor launch`. One local Harbor backend, four
# consumption patterns for host coding tools:
#
#   1. Direct launch   - `harbor launch <tool>` discovers the backend and model
#   2. Config-only     - `harbor launch --config <tool>` writes the adapter
#   3. Boost workflow  - `harbor launch --workflow <module> <tool>` routes through Boost
#   4. Web tools       - `harbor launch --web <tool>` adds web search and URL reading
#
# Layout (2x2 tmux grid):
#   +--------------+--------------+
#   | Title        | Config       |
#   |              | (--config)   |
#   +--------------+--------------+
#   | Workflow     | Web tools    |
#   | (--workflow) | (--web)      |
#   +--------------+--------------+
#
# Setup:
#   1. Install tmux: apt install tmux  (or brew install tmux on macOS)
#   2. Add Harbor to PATH: export PATH="$PWD:$PATH"
#   3. Start a backend and Boost: harbor up llamacpp boost
#   4. Install the host CLIs you want to demo: codex, claude, opencode, mi, hermes, pi, grok
#   5. Run the script: ./scripts/demos/launch-showcase.sh
#
# Usage:
#   ./scripts/demos/launch-showcase.sh
#   ./scripts/demos/launch-showcase.sh --dry-run
#   ./scripts/demos/launch-showcase.sh --backend ollama --model qwen3.5:4b
#   ./scripts/demos/launch-showcase.sh --workflow deephop --task "What changed in Python 3.13?" --yes

set -euo pipefail

SESSION="harbor-launch-showcase-$$"

BACKEND="${HARBOR_DEMO_BACKEND:-llamacpp}"
MODEL="${HARBOR_DEMO_MODEL:-unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL}"
WORKFLOW="${HARBOR_DEMO_WORKFLOW:-caveman}"

CONFIG_TOOL="${HARBOR_DEMO_CONFIG_TOOL:-codex}"
WORKFLOW_TOOL="${HARBOR_DEMO_WORKFLOW_TOOL:-codex}"
WEB_TOOL="${HARBOR_DEMO_WEB_TOOL:-hermes}"
TASK="${HARBOR_DEMO_TASK:-}"

DRY_RUN=false
SKIP_PROMPT=false

while [ $# -gt 0 ]; do
    case "$1" in
    --backend)
        [ -n "${2:-}" ] || { echo "Usage: --backend <service>" >&2; exit 1; }
        BACKEND="$2"; shift 2 ;;
    --model)
        [ -n "${2:-}" ] || { echo "Usage: --model <model-id>" >&2; exit 1; }
        MODEL="$2"; shift 2 ;;
    --workflow)
        [ -n "${2:-}" ] || { echo "Usage: --workflow <module>" >&2; exit 1; }
        WORKFLOW="$2"; shift 2 ;;
    --config-tool)
        [ -n "${2:-}" ] || { echo "Usage: --config-tool <tool>" >&2; exit 1; }
        CONFIG_TOOL="$2"; shift 2 ;;
    --workflow-tool)
        [ -n "${2:-}" ] || { echo "Usage: --workflow-tool <tool>" >&2; exit 1; }
        WORKFLOW_TOOL="$2"; shift 2 ;;
    --web-tool)
        [ -n "${2:-}" ] || { echo "Usage: --web-tool <tool>" >&2; exit 1; }
        WEB_TOOL="$2"; shift 2 ;;
    --task)
        [ -n "${2:-}" ] || { echo "Usage: --task <prompt>" >&2; exit 1; }
        TASK="$2"; shift 2 ;;
    --yes)
        SKIP_PROMPT=true; shift ;;
    --dry-run)
        DRY_RUN=true; shift ;;
    -h|--help)
        cat <<'HELP'
Usage: launch-showcase.sh [OPTIONS]

Options:
  --backend SERVICE       Harbor backend (default: llamacpp)
  --model ID              Model passed to the backend (default: unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL)
  --workflow MODULE       Boost workflow module (default: caveman)
  --config-tool TOOL      Tool for the config pane (default: codex)
  --workflow-tool TOOL    Tool for the workflow pane (default: codex)
  --web-tool TOOL         Tool for the web pane (default: hermes)
  --task PROMPT           Prompt sent to the workflow and web panes
  --yes                   Skip the confirmation prompt
  --dry-run               Print the commands that would run and exit
  -h, --help              Show this help

Environment variables:
  HARBOR_DEMO_BACKEND      Default backend
  HARBOR_DEMO_MODEL        Default model
  HARBOR_DEMO_WORKFLOW     Default workflow module
  HARBOR_DEMO_CONFIG_TOOL  Default tool for --config pane
  HARBOR_DEMO_WORKFLOW_TOOL Default tool for --workflow pane
  HARBOR_DEMO_WEB_TOOL     Default tool for --web pane
  HARBOR_DEMO_TASK         Default prompt

Examples:
  # Default 2x2 showcase
  ./scripts/demos/launch-showcase.sh

  # Use Ollama backend and a smaller model
  ./scripts/demos/launch-showcase.sh --backend ollama --model qwen3.5:4b

  # Research workflow demo
  ./scripts/demos/launch-showcase.sh --workflow quickhop --task "latest rust news"
HELP
        exit 0 ;;
    *)
        echo "Unknown option: $1" >&2
        exit 1 ;;
    esac
done

if [ -z "$TASK" ]; then
    case "$WORKFLOW" in
    caveman)   TASK="Explain the value of local LLM backends in one sentence." ;;
    quickhop)  TASK="What is the latest stable release of Python?" ;;
    deephop)   TASK="Summarize the current state of open-weights large language models." ;;
    *)         TASK="What can harbor launch do?" ;;
    esac
fi

shell_quote() {
    printf '%q' "$1"
}

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

log_info() {
    echo "-> $*"
}

log_warn() {
    echo "WARNING: $*" >&2
}

log_error() {
    echo "ERROR: $*" >&2
}

tool_prompt_args() {
    local tool="$1" prompt="$2"
    case "$tool" in
    codex)     printf 'exec --skip-git-repo-check --sandbox read-only --color never %q' "$prompt" ;;
    claude)    printf -- '-p %q' "$prompt" ;;
    opencode)  printf 'run %q' "$prompt" ;;
    hermes)    printf 'chat -Q -q %q' "$prompt" ;;
    mi)        printf -- '-p %q' "$prompt" ;;
    pi)        printf -- '-p %q' "$prompt" ;;
    grok)      printf -- '-p %q --no-wait-for-background' "$prompt" ;;
    *)         printf '%q' "$prompt" ;;
    esac
}

tool_config_label() {
    local tool="$1"
    case "$tool" in
    codex)     echo "OpenAI Codex" ;;
    claude)    echo "Claude Code" ;;
    opencode)  echo "OpenCode" ;;
    hermes)    echo "Hermes Agent" ;;
    mi)        echo "mi" ;;
    pi)        echo "pi" ;;
    grok)      echo "Grok" ;;
    *)         echo "$tool" ;;
    esac
}

workflow_description() {
    case "$WORKFLOW" in
    caveman)   echo "caveman adds terse-output rules before the final completion." ;;
    quickhop)  echo "quickhop does a short web-research pass before answering." ;;
    deephop)   echo "deephop does a two-hop research pass with gap checking." ;;
    *)         echo "${WORKFLOW} is passed to Boost as the selected module." ;;
    esac
}

check_prerequisites() {
    if ! cmd_exists tmux; then
        log_error "tmux is required. Install it (e.g. apt install tmux)."
        exit 1
    fi

    if ! cmd_exists harbor; then
        log_error "harbor is not on PATH. Add the Harbor repo to PATH."
        exit 1
    fi

    if ! cmd_exists curl; then
        log_warn "curl is not installed; skipping live backend checks."
    fi
}

ensure_backend() {
    if ! harbor ps 2>/dev/null | grep -qE "\\b${BACKEND}\\b"; then
        if [ "$DRY_RUN" = true ]; then
            log_warn "Backend '$BACKEND' is not running. Would start: harbor up ${BACKEND}"
        else
            log_warn "Backend '$BACKEND' is not running. Starting: harbor up ${BACKEND}"
            harbor up "${BACKEND}"
        fi
    fi
}

ensure_boost() {
    if ! harbor ps 2>/dev/null | grep -qE '\\bboost\\b'; then
        if [ "$DRY_RUN" = true ]; then
            log_warn "boost is not running. Would start: harbor up boost"
        else
            log_warn "boost is not running. Starting: harbor up boost"
            harbor up boost
        fi
    fi
}

ensure_searxng() {
    if ! harbor ps 2>/dev/null | grep -qE '\\bsearxng\\b'; then
        if [ "$DRY_RUN" = true ]; then
            log_warn "searxng is not running. Would start: harbor up searxng"
        else
            log_warn "searxng is not running. Starting: harbor up searxng"
            harbor up searxng
        fi
    fi
}

find_glow() {
    if command -v glow >/dev/null 2>&1; then
        echo "glow"
    elif [ -x "${HOME}/.local/bin/glow" ]; then
        echo "${HOME}/.local/bin/glow"
    else
        echo ""
    fi
}

build_title_file() {
    local file="$1"
    {
        echo "# Harbor Launch Showcase"
        echo
        echo "This demo shows four ways to consume the same local Harbor backend from a host coding tool."
        echo
        echo "## Backend"
        echo
        echo "- Backend: ${BACKEND}"
        echo "- Model: ${MODEL}"
        echo
        echo "## What each pane demonstrates"
        echo
        echo "1. Direct launch (not shown in a pane)"
        echo "   \`harbor launch <tool>\` discovers the running backend and model, then writes the adapter and starts the tool."
        echo
        echo "2. Config-only (top-right)"
        echo "   \`harbor launch --config ${CONFIG_TOOL}\` writes the adapter config without starting the tool."
        echo "   Tool: $(tool_config_label "${CONFIG_TOOL}")"
        echo
        echo "3. Boost workflow (bottom-left)"
        echo "   \`harbor launch --workflow ${WORKFLOW} ${WORKFLOW_TOOL} ...\` routes the tool through Boost."
        echo "   Tool: $(tool_config_label "${WORKFLOW_TOOL}")"
        echo "   Behavior: $(workflow_description)"
        echo
        echo "4. Web tools (bottom-right)"
        echo "   \`harbor launch --web ${WEB_TOOL} ...\` adds web search and URL reading to the agent."
        echo "   Tool: $(tool_config_label "${WEB_TOOL}")"
        echo
        echo "## Prompt"
        echo
        echo "${TASK}"
    } > "$file"
}

build_pane_command() {
    local pane="$1" tool="$2" prompt_args="$3"
    local backend_flags
    backend_flags="--backend ${BACKEND} --model $(shell_quote "$MODEL")"

    case "$pane" in
    config)
        echo "harbor launch ${backend_flags} --config $(shell_quote "$tool")"
        ;;
    workflow)
        echo "harbor launch ${backend_flags} --workflow $(shell_quote "$WORKFLOW") $(shell_quote "$tool") ${prompt_args}"
        ;;
    web)
        echo "harbor launch --web ${backend_flags} $(shell_quote "$tool") ${prompt_args}"
        ;;
    esac
}

build_pane_display() {
    local pane="$1" tool="$2" prompt="$3"
    local prompt_args
    prompt_args=$(tool_prompt_args "$tool" "$prompt")
    build_pane_command "$pane" "$tool" "$prompt_args"
}

build_pane_label() {
    local pane="$1"
    case "$pane" in
    title)    echo "[intro] Harbor Launch" ;;
    config)   echo "[config] --config ${CONFIG_TOOL}" ;;
    workflow) echo "[workflow] --workflow ${WORKFLOW} ${WORKFLOW_TOOL}" ;;
    web)      echo "[web] --web ${WEB_TOOL}" ;;
    esac
}

run_pane_command() {
    local pane="$1" tool="$2" prompt="$3"
    local prompt_args cmd

    prompt_args=$(tool_prompt_args "$tool" "$prompt")
    cmd=$(build_pane_command "$pane" "$tool" "$prompt_args")

    if [ "$pane" = "config" ]; then
        echo "$cmd"
        return 0
    fi

    if ! cmd_exists "$tool"; then
        echo "echo 'Host tool ${tool} is not installed. Install it on your host (not via Harbor) to see this pane in action.'"
        echo "echo 'The command that would run is:'"
        echo "echo $(shell_quote "$cmd")"
        return 0
    fi

    echo "$cmd"
}

print_dry_run() {
    echo
    echo "===== Dry run ====="
    printf "%-12s %s\n" "Pane" "Command"
    printf "%-12s %s\n" "config"   "$(build_pane_display config   "$CONFIG_TOOL"   "$TASK")"
    printf "%-12s %s\n" "workflow" "$(build_pane_display workflow "$WORKFLOW_TOOL" "$TASK")"
    printf "%-12s %s\n" "web"      "$(build_pane_display web      "$WEB_TOOL"      "$TASK")"
    echo
}

prepare_environment() {
    check_prerequisites

    ensure_backend
    ensure_boost
    ensure_searxng

    if [ "$DRY_RUN" = true ]; then
        print_dry_run
        exit 0
    fi

    echo
    log_info "Backend:  ${BACKEND}"
    log_info "Model:    ${MODEL}"
    log_info "Workflow: ${WORKFLOW}"
    log_info "Task:     ${TASK}"
    log_info "Panes:    config=${CONFIG_TOOL}, workflow=${WORKFLOW_TOOL}, web=${WEB_TOOL}"
    echo

    if [ "$SKIP_PROMPT" = false ] && [ -t 0 ]; then
        read -r -p "Press Enter to start the demo..."
    fi
}

setup_tmux() {
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    tmux new-session -d -s "$SESSION" -n showcase -x 160 -y 50

    # 2x2 grid: split right, then split each half horizontally.
    tmux split-window -h -t "$SESSION:showcase.0"
    tmux split-window -v -t "$SESSION:showcase.0"
    tmux split-window -v -t "$SESSION:showcase.1"

    tmux select-layout -t "$SESSION:showcase" tiled

    tmux set-option -t "$SESSION" status on
    tmux set-option -t "$SESSION" status-interval 1
    tmux set-option -t "$SESSION" status-left " #[bg=colour26,fg=colour231,bold] Harbor Launch #[default] "
    tmux set-option -t "$SESSION" status-right " #[bg=colour28,fg=colour231] ${BACKEND} / ${MODEL} #[default] "
    tmux set-option -t "$SESSION" pane-border-status top
    tmux set-option -t "$SESSION" pane-border-format " #{pane_title} "
    tmux set-option -t "$SESSION" pane-border-style "fg=colour240"
    tmux set-option -t "$SESSION" pane-active-border-style "fg=colour26,bold"
}

send_to_pane() {
    local index="$1" title="$2" cmd="$3"
    local target="$SESSION:showcase.$index"

    tmux select-pane -t "$target" -T "$title"
    tmux send-keys -t "$target" "clear" C-m
    tmux send-keys -t "$target" "printf '\\033[1;34m[%s]\\033[0m\\n' $(shell_quote "$title")" C-m
    tmux send-keys -t "$target" "$cmd" C-m
}

launch_showcase() {
    local title_file
    title_file=$(mktemp "/tmp/harbor-launch-showcase-${SESSION}-title-XXXXXX.md")
    build_title_file "$title_file"

    local glow_bin
    glow_bin=$(find_glow)
    if [ -n "$glow_bin" ]; then
        send_to_pane 0 "$(build_pane_label title)" "$(shell_quote "$glow_bin") $(shell_quote "$title_file")"
    else
        send_to_pane 0 "$(build_pane_label title)" "cat $(shell_quote "$title_file")"
    fi

    send_to_pane 1 "$(build_pane_label config)"   "$(run_pane_command config   "$CONFIG_TOOL"   "$TASK")"
    send_to_pane 2 "$(build_pane_label workflow)" "$(run_pane_command workflow "$WORKFLOW_TOOL" "$TASK")"
    send_to_pane 3 "$(build_pane_label web)"      "$(run_pane_command web      "$WEB_TOOL"      "$TASK")"
}

prepare_environment
setup_tmux
launch_showcase

echo
log_info "Attaching to tmux session: ${SESSION}"
log_info "Top-right:    config-only mode"
log_info "Bottom-left:  Boost workflow"
log_info "Bottom-right: web tools"
log_info "Detach with Ctrl+b then d. Stop Harbor later with: harbor down"
echo

tmux attach-session -t "$SESSION"
