#!/usr/bin/env bash
# Harbor Launch Grid Demo
#
# Harbor (this repo) is a containerized local LLM toolkit, not the container
# registry. This script creates a single tmux window with 2-4 panes, each
# launching a different coding assistant through the `harbor launch` command.
# Every pane is pointed at the same local model backend, and the same research
# question is asked in each pane.
#
# The default grid is a 4-pane layout: 3 coding-assistant panes all using the
# same Boost workflow, plus 1 intro pane that explains the setup to the viewer.
# Every pane is pointed at the same local model backend and the same research
# question is asked in each assistant pane.
#
# Designed for readability: maximize your terminal font size and use at most
# 4 panes. Run the script multiple times with different --tools to "scale" the
# demo and show more assistants without crowding the screen.
#
# Setup:
#   1. Install tmux: apt install tmux  (or brew install tmux on macOS)
#   2. Install glow for the title pane: see --help for a one-line curl command
#   3. Add Harbor to PATH: export PATH="$PWD:$PATH"
#   4. Start the backend and Boost:
#        harbor up ollama boost
#   5. Install the host coding assistants you want to demo (codex, opencode, hermes, ...)
#   6. Run the script: ./scripts/demos/launch-grid.sh
#
# Prerequisites:
#   - tmux installed
#   - glow installed (recommended for the title pane; falls back to cat)
#   - harbor on PATH
#   - a running Harbor backend (ollama, llama.cpp, etc.) with a model loaded
#   - the selected coding tools installed on the host
#   - jq installed if you use pi or opencode (required for config merging)
#   - Docker / Docker Compose for Harbor services
#   - For quickhop/deephop research workflows: a working SearXNG or Tavily key
#     (set HARBOR_BOOST_TAVILY_API_KEY). Otherwise research falls back to the
#     model's knowledge.
#
# Usage:
#   ./scripts/demos/launch-grid.sh
#   ./scripts/demos/launch-grid.sh --panes 2 --tools codex,opencode
#   ./scripts/demos/launch-grid.sh --tools codex,opencode,hermes,title
#   ./scripts/demos/launch-grid.sh --workflow deephop --tools codex,opencode,hermes,title
#   ./scripts/demos/launch-grid.sh --workflow caveman --tools codex,opencode,hermes,title
#   ./scripts/demos/launch-grid.sh --record demo.cast --yes --tools codex,opencode,hermes,title
#   ./scripts/demos/launch-grid.sh --duration 45 --yes --tools codex,opencode,hermes,title
#   ./scripts/demos/launch-grid.sh --dry-run

set -euo pipefail

# Unique session name so repeated runs do not clobber each other.
SESSION_NAME="harbor-launch-grid-$$"
BACKEND="${HARBOR_DEMO_BACKEND:-llamacpp}"
MODEL="${HARBOR_DEMO_MODEL:-unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL}"
WORKFLOW="${HARBOR_DEMO_WORKFLOW:-caveman}"
TASK="${HARBOR_DEMO_TASK:-}"

PANES=4
TOOLS="codex,opencode,hermes,title"
AUTO_PROMPT=true
DRY_RUN=false
SKIP_PROMPT=false
SKIP_MISSING=false
RECORD_FILE=""
DURATION=0
DEMO_WATCHER_RESULT=""
DEMO_DONE_DIR=""
DEMO_ASSISTANT_COUNT=0

SELECTED_TOOLS=()
declare -A TOOL_CMD
declare -A TOOL_DISPLAY_CMD
declare -A TOOL_PROMPT
declare -A TOOL_PROMPT_DISPLAY
declare -A TOOL_QUIET_STDERR
declare -A TOOL_TITLE

# Preserve original arguments for the --record wrapper.
ORIGINAL_ARGS=("$@")

while [ $# -gt 0 ]; do
    case "$1" in
    --panes)
        if [ -z "${2:-}" ]; then
            echo "Usage: --panes 2|3|4" >&2
            exit 1
        fi
        PANES="$2"
        shift 2
        ;;
    --tools)
        if [ -z "${2:-}" ]; then
            echo "Usage: --tools claude,codex,grok,opencode,hermes,pi,title" >&2
            exit 1
        fi
        TOOLS="$2"
        shift 2
        ;;
    --backend)
        if [ -z "${2:-}" ]; then
            echo "Usage: --backend llamacpp|ollama|..." >&2
            exit 1
        fi
        BACKEND="$2"
        shift 2
        ;;
    --model)
        if [ -z "${2:-}" ]; then
            echo "Usage: --model <model-id>" >&2
            exit 1
        fi
        MODEL="$2"
        shift 2
        ;;
    --workflow)
        if [ -z "${2:-}" ]; then
            echo "Usage: --workflow quickhop|deephop|caveman" >&2
            exit 1
        fi
        WORKFLOW="$2"
        shift 2
        ;;
    --auto-prompt)
        AUTO_PROMPT=true
        shift
        ;;
    --no-auto-prompt)
        AUTO_PROMPT=false
        shift
        ;;
    --skip-missing)
        SKIP_MISSING=true
        shift
        ;;
    --yes)
        SKIP_PROMPT=true
        shift
        ;;
    --record)
        if [ -z "${2:-}" ]; then
            echo "Usage: --record <output.cast>" >&2
            exit 1
        fi
        RECORD_FILE="$2"
        shift 2
        ;;
    --duration)
        if [ -z "${2:-}" ]; then
            echo "Usage: --duration <seconds>" >&2
            exit 1
        fi
        if ! [[ "${2:-}" =~ ^[0-9]+$ ]]; then
            echo "--duration must be a positive integer (seconds)" >&2
            exit 1
        fi
        DURATION="$2"
        shift 2
        ;;
    --dry-run)
        DRY_RUN=true
        shift
        ;;
    -h | --help)
        cat <<'HELP'
Usage: launch-grid.sh [OPTIONS]

Options:
  --panes 2|3|4         Number of tmux panes (default: 4)
  --tools LIST          Comma-separated tools: claude, codex, grok, opencode, hermes, pi, title
                        (default: codex,opencode,hermes,title)
  --backend SERVICE     Harbor backend to use: ollama, llamacpp, ... (default: llamacpp)
  --model ID            Model passed to backends that need one (default: unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL)
  --workflow MODULE     Boost workflow applied to every assistant pane: quickhop, deephop, caveman
                        (default: caveman)
  --auto-prompt         Pass the task as a CLI argument to each tool that supports it
                        (this is the default)
  --no-auto-prompt      Open the tools and let you type the task manually
  --skip-missing        Omit tools that are not installed instead of opening failing panes
  --yes                 Skip the confirmation prompt
  --record FILE         Record the demo with asciinema to FILE (requires asciinema)
  --duration SECONDS    Run autonomously for SECONDS, then exit tmux (for screen recording)
  --dry-run             Print the commands that would run and exit
  -h, --help            Show this help

Environment variables:
  HARBOR_DEMO_BACKEND   Default backend (default: llamacpp)
  HARBOR_DEMO_MODEL     Default model for backends that need --model (default: unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL)
  HARBOR_DEMO_WORKFLOW  Default Boost workflow (default: caveman)
  HARBOR_DEMO_TASK      Prompt sent to every assistant pane; defaults by workflow

Install glow for the title pane:
  curl -fsSL https://github.com/charmbracelet/glow/releases/download/v2.1.2/glow_2.1.2_Linux_x86_64.tar.gz | tar -xz -O glow_2.1.2_Linux_x86_64/glow > ~/.local/bin/glow

Examples:
  # Default 4-pane demo: 3 assistants + 1 intro pane, all using caveman
  ./scripts/demos/launch-grid.sh

  # Two-pane contrast: codex vs opencode
  ./scripts/demos/launch-grid.sh --panes 2 --tools codex,opencode

  # Three assistants + title, all with deephop
  ./scripts/demos/launch-grid.sh --workflow deephop --tools codex,opencode,hermes,title

  # Style demo: caveman terse-output workflow
  ./scripts/demos/launch-grid.sh --workflow caveman --tools codex,opencode,hermes,title

  # Research demo: quickhop/deephop need web search (SearXNG or Tavily)
  ./scripts/demos/launch-grid.sh --workflow quickhop --tools codex,opencode,hermes,title

  # Pin the demo backend and model explicitly
  ./scripts/demos/launch-grid.sh --backend llamacpp --model unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL --tools codex,opencode,hermes,title

  # Record the demo to share
  ./scripts/demos/launch-grid.sh --record demo.cast --yes --tools codex,opencode,hermes,title

  # Autonomous screen-recording run: 45 seconds then exit
  ./scripts/demos/launch-grid.sh --duration 45 --yes --tools codex,opencode,hermes,title

  # Scale: run multiple grids in sequence to avoid crowding the screen
  ./scripts/demos/launch-grid.sh --tools codex,opencode,hermes,title
  ./scripts/demos/launch-grid.sh --panes 3 --tools grok,pi,title
HELP
        exit 0
        ;;
    *)
        echo "Unknown option: $1" >&2
        exit 1
        ;;
    esac
done

# Reject pane counts outside the supported 2-4 range.
if ! [[ "$PANES" =~ ^[234]$ ]]; then
    echo "--panes must be 2, 3, or 4" >&2
    exit 1
fi

# If --record was requested, start an asciinema recording of this same script
# without the --record argument, so the demo is fully captured.
start_recording() {
    if ! command -v asciinema >/dev/null 2>&1; then
        echo "ERROR: asciinema is required for --record. Install it from https://asciinema.org/." >&2
        exit 1
    fi

    # Build the inner command without --record to avoid recursion.
    local inner_args=()
    local skip_next=false
    local arg
    for arg in "${ORIGINAL_ARGS[@]}"; do
        if [ "$skip_next" = true ]; then
            skip_next=false
            continue
        fi
        if [ "$arg" = "--record" ]; then
            skip_next=true
            continue
        fi
        inner_args+=("$arg")
    done

    # Force non-interactive, auto-prompted behavior for a clean recording.
    inner_args+=("--yes" "--auto-prompt")

    echo "Recording demo to ${RECORD_FILE}"
    echo "Detach from tmux with Ctrl+b, then d when you are done."
    export HARBOR_DEMO_RECORDING=true
    exec asciinema rec "$RECORD_FILE" -c "$0 ${inner_args[*]}"
}

if [ -n "$RECORD_FILE" ] && [ "${HARBOR_DEMO_RECORDING:-false}" != "true" ]; then
    start_recording
fi

# Colors
if [ -t 1 ]; then
    BOLD=$(tput bold)
    BLUE=$(tput setaf 4)
    GREEN=$(tput setaf 2)
    YELLOW=$(tput setaf 3)
    RED=$(tput setaf 1)
    RESET=$(tput sgr0)
else
    BOLD=""
    BLUE=""
    GREEN=""
    YELLOW=""
    RED=""
    RESET=""
fi

banner() {
    echo "${BOLD}${BLUE}==>${RESET} ${BOLD}$*${RESET}"
}

info() {
    echo "${GREEN}->${RESET} $*"
}

warn() {
    echo "${YELLOW}WARNING:${RESET} $*"
}

error() {
    echo "${RED}ERROR:${RESET} $*"
}

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

big_title() {
    if cmd_exists figlet; then
        figlet -f slant "$1"
    elif cmd_exists gum; then
        gum style --border double --padding "1 2" --align center "$1"
    else
        echo "===== $1 ====="
    fi
}

# Safely quote a string for use in a shell command.
shell_quote() {
    printf '%q' "$1"
}

# Locate the glow binary for the title pane. Fall back to the user-local
# install path if it is not on PATH.
find_glow() {
    if command -v glow >/dev/null 2>&1; then
        echo "glow"
    elif [ -x "${HOME}/.local/bin/glow" ]; then
        echo "${HOME}/.local/bin/glow"
    else
        echo ""
    fi
}

# Build the --backend, --model, and --workflow flags for the current backend.
# Every pane gets the same model and workflow so the comparison is fair.
build_backend_flags() {
    local flags
    flags="--backend ${BACKEND} --model $(shell_quote "$MODEL")"
    if [ -n "$WORKFLOW" ]; then
        flags="${flags} --workflow $(shell_quote "$WORKFLOW")"
    fi
    echo "$flags"
}

default_task_for_workflow() {
    case "$WORKFLOW" in
    caveman)
        echo "Say exactly: Tool route. Boost shape. Local model answer."
        ;;
    quickhop)
        echo "Say exactly: Quickhop search brief first; model answers after."
        ;;
    deephop)
        echo "Say exactly: Deephop checks first pass, fills gaps, then answers."
        ;;
    *)
        echo "Say exactly: Harbor launch routes this agent through Boost."
        ;;
    esac
}

workflow_behavior() {
    case "$WORKFLOW" in
    caveman)
        echo "caveman adds terse-output rules before final completion."
        ;;
    quickhop)
        echo "quickhop runs a small web-research pass on research turns, then injects a brief."
        ;;
    deephop)
        echo "deephop does deeper two-hop research: search, gap check, follow-up, then answer."
        ;;
    "")
        echo "No Boost workflow is selected; tools talk directly to the backend."
        ;;
    *)
        echo "${WORKFLOW} is passed to Boost as the selected module workflow."
        ;;
    esac
}

# Register a supported tool (or the special title pane).
configure_tool() {
    local tool="$1"
    local backend_flags
    backend_flags=$(build_backend_flags)

    case "$tool" in
    claude)
        TOOL_CMD[claude]="harbor launch ${backend_flags} claude"
        TOOL_DISPLAY_CMD[claude]="${TOOL_CMD[claude]}"
        TOOL_PROMPT[claude]="-p $(shell_quote "$TASK")"
        TOOL_PROMPT_DISPLAY[claude]="-p \"${TASK}\""
        TOOL_QUIET_STDERR[claude]=true
        TOOL_TITLE[claude]="[raw] claude"
        ;;
    codex)
        local codex_log
        local codex_filter
        local codex_inner
        codex_log=$(mktemp "/tmp/harbor-launch-grid-${SESSION_NAME}-codex-XXXXXX.log")
        codex_filter='fromjson? | select(.type == "item.completed" and .item.type == "agent_message") | .item.text'
        codex_inner="harbor launch ${backend_flags} codex exec --json $(shell_quote "$TASK") 2>$(shell_quote "$codex_log") | jq -Rr $(shell_quote "$codex_filter"); status=\${PIPESTATUS[0]}; if [ \"\$status\" -ne 0 ]; then cat $(shell_quote "$codex_log") >&2; exit \"\$status\"; fi"
        TOOL_CMD[codex]="bash -lc $(shell_quote "$codex_inner")"
        TOOL_DISPLAY_CMD[codex]="harbor launch ${backend_flags} codex"
        TOOL_PROMPT[codex]=""
        TOOL_PROMPT_DISPLAY[codex]="exec \"${TASK}\""
        TOOL_QUIET_STDERR[codex]=false
        TOOL_TITLE[codex]="[workflow] codex + ${WORKFLOW}"
        ;;
    grok)
        TOOL_CMD[grok]="harbor launch ${backend_flags} grok"
        TOOL_DISPLAY_CMD[grok]="${TOOL_CMD[grok]}"
        TOOL_PROMPT[grok]="-p $(shell_quote "$TASK") --no-wait-for-background"
        TOOL_PROMPT_DISPLAY[grok]="-p \"${TASK}\" --no-wait-for-background"
        TOOL_QUIET_STDERR[grok]=true
        TOOL_TITLE[grok]="[workflow] grok + ${WORKFLOW}"
        ;;
    opencode)
        TOOL_CMD[opencode]="harbor launch ${backend_flags} opencode"
        TOOL_DISPLAY_CMD[opencode]="${TOOL_CMD[opencode]}"
        TOOL_PROMPT[opencode]="run $(shell_quote "$TASK")"
        TOOL_PROMPT_DISPLAY[opencode]="run \"${TASK}\""
        TOOL_QUIET_STDERR[opencode]=true
        TOOL_TITLE[opencode]="[workflow] opencode + ${WORKFLOW}"
        ;;
    hermes)
        TOOL_CMD[hermes]="harbor launch ${backend_flags} hermes"
        TOOL_DISPLAY_CMD[hermes]="${TOOL_CMD[hermes]}"
        TOOL_PROMPT[hermes]="chat -Q -q $(shell_quote "$TASK")"
        TOOL_PROMPT_DISPLAY[hermes]="chat -Q -q \"${TASK}\""
        TOOL_QUIET_STDERR[hermes]=true
        TOOL_TITLE[hermes]="[workflow] hermes + ${WORKFLOW}"
        ;;
    pi)
        # Unique session dir per run so stale pi sessions never hang the demo.
        local pi_session_dir
        pi_session_dir=$(mktemp -d "/tmp/harbor-launch-grid-${SESSION_NAME}-pi-XXXXXX")
        TOOL_CMD[pi]="harbor launch ${backend_flags} pi"
        TOOL_DISPLAY_CMD[pi]="${TOOL_CMD[pi]}"
        TOOL_PROMPT[pi]="--session-dir $(shell_quote "$pi_session_dir") -p $(shell_quote "$TASK")"
        TOOL_PROMPT_DISPLAY[pi]="--session-dir ${pi_session_dir} -p \"${TASK}\""
        TOOL_QUIET_STDERR[pi]=true
        TOOL_TITLE[pi]="[workflow] pi + ${WORKFLOW}"
        ;;
    title)
        # Title/explainer pane rendered with glow (or cat as a fallback).
        local title_file
        title_file=$(mktemp "/tmp/harbor-launch-grid-${SESSION_NAME}-title-XXXXXX.md")
        {
            echo "# Harbor Launch Grid Demo"
            echo
            echo "Same prompt, same local model, different agent harnesses."
            echo
            echo "## What is happening"
            echo
            echo "1. harbor launch starts or reuses **${BACKEND}**."
            echo "2. It points each host tool at **${MODEL}**."
            echo "3. It routes requests through Boost with **${WORKFLOW}**."
            echo "4. Each pane runs a different agent CLI against that same route."
            echo
            echo "## Workflow behavior"
            echo
            workflow_behavior
            echo
            echo "## Compare panes"
            echo
            echo "- Same prompt: ${TASK}"
            echo "- Same model and workflow."
            echo "- Different harness UI, startup, and final rendering."
            echo
            echo "Try next: \`--workflow quickhop\` or \`--workflow deephop\`."
        } > "$title_file"
        local glow_bin
        glow_bin=$(find_glow)
        if [ -n "$glow_bin" ]; then
            TOOL_CMD[title]="$(shell_quote "$glow_bin") $(shell_quote "$title_file")"
        else
            TOOL_CMD[title]="cat $(shell_quote "$title_file")"
        fi
        TOOL_DISPLAY_CMD[title]="${TOOL_CMD[title]}"
        TOOL_PROMPT[title]=""
        TOOL_PROMPT_DISPLAY[title]=""
        TOOL_QUIET_STDERR[title]=false
        TOOL_TITLE[title]="[intro] Demo"
        ;;
    esac
}

# Parse the comma-separated --tools list into SELECTED_TOOLS.
parse_toolset() {
    local tools_str="$1"
    local tool
    local tool_count=0
    local title_count=0
    local total_count=0

    SELECTED_TOOLS=()

    IFS=',' read -ra raw_tools <<< "$tools_str"

    for tool in "${raw_tools[@]}"; do
        tool=$(echo "$tool" | tr -d '[:space:]')
        case "$tool" in
        claude | codex | grok | opencode | hermes | pi)
            configure_tool "$tool"
            SELECTED_TOOLS+=("$tool")
            tool_count=$((tool_count + 1))
            ;;
        title)
            configure_tool "title"
            SELECTED_TOOLS+=("title")
            title_count=$((title_count + 1))
            ;;
        "")
            ;;
        *)
            warn "Unknown tool '$tool'. Skipping."
            ;;
        esac
    done

    total_count=$((tool_count + title_count))

    if [ "$tool_count" -lt 2 ]; then
        error "At least 2 coding assistants are required for a grid demo."
        exit 1
    fi
    if [ "$title_count" -gt 1 ]; then
        error "Only one title pane is allowed."
        exit 1
    fi

    if [ "$total_count" -gt "$PANES" ]; then
        warn "You selected $total_count panes but requested $PANES. Using the first $PANES."
        SELECTED_TOOLS=("${SELECTED_TOOLS[@]:0:$PANES}")
    fi

    if [ "$total_count" -lt "$PANES" ]; then
        warn "You selected $total_count panes but requested $PANES. Reducing to $total_count panes."
        PANES=$total_count
    fi

    DEMO_ASSISTANT_COUNT=0
    for tool in "${SELECTED_TOOLS[@]}"; do
        if [ "$tool" != "title" ]; then
            DEMO_ASSISTANT_COUNT=$((DEMO_ASSISTANT_COUNT + 1))
        fi
    done
}

# Build the command that will actually be sent to a pane.
build_pane_command() {
    local tool="$1"
    local cmd="${TOOL_CMD[$tool]}"
    if [ "$AUTO_PROMPT" = true ] && [ -n "${TOOL_PROMPT[$tool]:-}" ]; then
        cmd="$cmd ${TOOL_PROMPT[$tool]}"
    fi
    if [ "${TOOL_QUIET_STDERR[$tool]:-false}" = true ]; then
        local stderr_log
        local inner
        stderr_log=$(mktemp "/tmp/harbor-launch-grid-${SESSION_NAME}-${tool}-stderr-XXXXXX.log")
        inner="${cmd} 2>$(shell_quote "$stderr_log"); status=\$?; if [ \"\$status\" -ne 0 ]; then cat $(shell_quote "$stderr_log") >&2; exit \"\$status\"; fi"
        cmd="bash -lc $(shell_quote "$inner")"
    fi
    echo "$cmd"
}

# Build a viewer-readable form of the pane command for dry-run output.
build_pane_display_command() {
    local tool="$1"
    local cmd="${TOOL_DISPLAY_CMD[$tool]:-${TOOL_CMD[$tool]}}"
    if [ "$tool" = "title" ]; then
        echo "intro pane rendered with glow when available"
        return 0
    fi
    if [ "$AUTO_PROMPT" = true ] && [ -n "${TOOL_PROMPT_DISPLAY[$tool]:-}" ]; then
        cmd="$cmd ${TOOL_PROMPT_DISPLAY[$tool]}"
    fi
    echo "$cmd"
}

# Check whether web search is actually usable. quickhop/deephop rely on it,
# so warn the viewer when the demo will fall back to the model's knowledge.
check_search_availability() {
    local tavily_key
    tavily_key=$(harbor config get HARBOR_BOOST_TAVILY_API_KEY 2>/dev/null || true)
    if [ -n "$tavily_key" ] && [ "$tavily_key" != '""' ]; then
        return 0
    fi

    local searxng_url
    searxng_url=$(harbor config get HARBOR_BOOST_SEARXNG_URL 2>/dev/null || echo "http://searxng:8080")
    # Strip surrounding quotes if the config manager returned a JSON string.
    searxng_url=${searxng_url#\"}
    searxng_url=${searxng_url%\"}
    if [ -z "$searxng_url" ]; then
        searxng_url="http://localhost:33811"
    fi

    if ! curl -fsS --max-time 5 "${searxng_url}/search?q=test&format=json" >/dev/null 2>&1; then
        warn "Web search is not available (SearXNG at ${searxng_url} is unreachable and no Tavily key is set)."
        warn "quickhop/deephop will fall back to the model's knowledge for this demo."
        warn "Set HARBOR_BOOST_TAVILY_API_KEY or fix SearXNG to see live research."
    fi
}

# Print the one-paragraph intro that viewers will see on screen.
print_demo_intro() {
    echo
    info "Same prompt, same backend/model, different agent harnesses."
    if [ -n "$WORKFLOW" ]; then
        info "Every assistant is routed through the ${WORKFLOW} Boost workflow."
    else
        info "All panes answer directly from the backend."
    fi
    echo
}

# Check prerequisites and prepare the environment.
prepare_environment() {
    big_title "Harbor Launch Grid"
    print_demo_intro

    if ! cmd_exists tmux; then
        error "tmux is required. Please install it first (e.g. apt install tmux)."
        exit 1
    fi

    if ! cmd_exists jq; then
        if [[ " ${SELECTED_TOOLS[*]} " == *" codex "* || " ${SELECTED_TOOLS[*]} " == *" pi "* || " ${SELECTED_TOOLS[*]} " == *" opencode"* ]]; then
            error "jq is required for the codex quiet wrapper and the pi/opencode adapters. Please install it."
            exit 1
        fi
    fi

    if ! cmd_exists harbor; then
        error "harbor is not on PATH. Add the Harbor repo to PATH, or run this script from the Harbor repo directory."
        exit 1
    fi

    info "Checking Harbor services..."

    if ! harbor ps 2>/dev/null | grep -qE "\\b${BACKEND}\\b"; then
        if [ "$DRY_RUN" = true ]; then
            warn "Backend '$BACKEND' is not running. Would start it with: harbor up ${BACKEND}"
        else
            warn "Backend '$BACKEND' is not running. Starting it with: harbor up ${BACKEND}"
            harbor up "${BACKEND}"
        fi
    fi

    if ! harbor ps 2>/dev/null | grep -qE '\\bboost\\b'; then
        if [ "$DRY_RUN" = true ]; then
            warn "boost is not running. Would start it with: harbor up boost"
        else
            warn "boost is not running. Starting it with: harbor up boost"
            harbor up boost
        fi
    fi

    # Research workflows need live web search; style workflows do not.
    if [ "$WORKFLOW" = "quickhop" ] || [ "$WORKFLOW" = "deephop" ]; then
        if ! harbor ps 2>/dev/null | grep -qE '\\bsearxng\\b'; then
            if [ "$DRY_RUN" = true ]; then
                warn "searxng is not running. Would start it with: harbor up searxng"
            else
                warn "searxng is not running. Starting it with: harbor up searxng"
                harbor up searxng
            fi
        fi
        if [ "$DRY_RUN" = false ]; then
            check_search_availability
        fi
    fi

    if [[ " ${SELECTED_TOOLS[*]} " == *" title "* ]] && [ -z "$(find_glow)" ]; then
        warn "glow is not installed. The title pane will use plain cat instead."
    fi

    if [ "$DRY_RUN" = false ]; then
        local tool
        local installed_tools=()
        local installed_assistants=0
        for tool in "${SELECTED_TOOLS[@]}"; do
            if [ "$tool" = "title" ]; then
                installed_tools+=("$tool")
                continue
            fi
            if cmd_exists "$tool"; then
                installed_tools+=("$tool")
                installed_assistants=$((installed_assistants + 1))
            else
                if [ "$SKIP_MISSING" = true ]; then
                    warn "Host CLI tool '$tool' is not installed. Skipping because --skip-missing is set."
                else
                    warn "Host CLI tool '$tool' is not installed. Its pane will fail unless you install it on your system (not via Harbor)."
                fi
            fi
        done
        if [ "$SKIP_MISSING" = true ]; then
            SELECTED_TOOLS=("${installed_tools[@]}")
            if [ "$installed_assistants" -lt 2 ]; then
                error "At least 2 installed tools are required for a grid demo."
                exit 1
            fi
            PANES=${#SELECTED_TOOLS[@]}
            if [ "$PANES" -gt 4 ]; then
                PANES=4
                SELECTED_TOOLS=("${SELECTED_TOOLS[@]:0:$PANES}")
            fi
            DEMO_ASSISTANT_COUNT=0
            for tool in "${SELECTED_TOOLS[@]}"; do
                if [ "$tool" != "title" ]; then
                    DEMO_ASSISTANT_COUNT=$((DEMO_ASSISTANT_COUNT + 1))
                fi
            done
        fi
    fi

    if [ "$DRY_RUN" = false ]; then
        check_model_readiness
    fi

    info "Panes:    ${BOLD}${PANES}${RESET}"
    info "Backend:  ${BOLD}${BACKEND}${RESET}"
    info "Model:    ${BOLD}${MODEL}${RESET}"
    info "Task:     ${BOLD}${TASK}${RESET}"
    if [ -n "$WORKFLOW" ]; then
        info "Workflow: ${BOLD}${WORKFLOW}${RESET}"
    fi
    info "Tools:    ${BOLD}${SELECTED_TOOLS[*]}${RESET}"
    echo

    if [ "$DRY_RUN" = true ]; then
        banner "Dry run"
        local i
        printf "%-12s %s\n" "Pane" "Command"
        for i in "${!SELECTED_TOOLS[@]}"; do
            local tool="${SELECTED_TOOLS[$i]}"
            printf "%-12s %s\n" "$((i + 1)). $tool" "$(build_pane_display_command "$tool")"
        done
        echo
        exit 0
    fi

    if [ "$AUTO_PROMPT" = true ]; then
        info "Auto-prompt is enabled. The task will be sent to every pane automatically."
    fi

    if [ "$SKIP_PROMPT" = false ] && [ -t 0 ]; then
        read -r -p "Press Enter to start the demo..."
    fi
}

# Verify that the backend is actually serving a model.
check_model_readiness() {
    if ! cmd_exists curl; then
        warn "curl is not installed; skipping model-readiness check."
        return 0
    fi

    local url
    url=$(harbor url "$BACKEND" 2>/dev/null || true)
    if [ -z "$url" ]; then
        warn "Could not determine a URL for backend '$BACKEND'."
        return 1
    fi

    local base_url
    base_url="${url%/}"
    if curl -fsS --max-time 5 "${base_url}/v1/models" >/dev/null 2>&1; then
        return 0
    fi
    if curl -fsS --max-time 5 "${base_url}/models" >/dev/null 2>&1; then
        return 0
    fi

    warn "Backend '$BACKEND' is not advertising any models at ${base_url}."
    warn "Load a model before running the demo, or switch to a backend like ollama with --backend."
}

# Create a fresh tmux session with a 2-4 pane grid.
setup_tmux() {
    # Kill only our own unique session; do not touch other tmux sessions.
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

    # Use a roomy default terminal size so code panes have enough columns even
    # when the session is created before the viewer attaches. tmux resizes to
    # the actual client when the user attaches, but the default prevents tiny
    # 80x24 detached sessions that make code output wrap badly.
    tmux new-session -d -s "$SESSION_NAME" -n "grid" -x 160 -y 50

    case "$PANES" in
    2)
        tmux split-window -h -t "$SESSION_NAME:grid.0"
        ;;
    3)
        tmux split-window -h -t "$SESSION_NAME:grid.0"
        tmux split-window -v -t "$SESSION_NAME:grid.1"
        ;;
    4)
        tmux split-window -h -t "$SESSION_NAME:grid.0"
        tmux split-window -v -t "$SESSION_NAME:grid.0"
        tmux split-window -v -t "$SESSION_NAME:grid.1"
        ;;
    esac

    tmux select-layout -t "$SESSION_NAME:grid" tiled

    tmux set-option -t "$SESSION_NAME" status on
    tmux set-option -t "$SESSION_NAME" status-interval 1
    tmux set-option -t "$SESSION_NAME" status-left "#[bg=colour26,fg=colour231,bold] Harbor | workflow grid #[default] "
    tmux set-option -t "$SESSION_NAME" status-right "#[bg=colour28,fg=colour231] ${BACKEND} ${MODEL} #[default]"
    tmux set-option -t "$SESSION_NAME" pane-border-status top
    tmux set-option -t "$SESSION_NAME" pane-border-format " #{pane_title} "
    tmux set-option -t "$SESSION_NAME" pane-border-style "fg=colour240"
    tmux set-option -t "$SESSION_NAME" pane-active-border-style "fg=colour26,bold"
}

# Send a banner and a launch command to a pane.
setup_pane() {
    local pane_index="$1"
    local tool="$2"
    local title="$3"
    local launch_cmd="$4"
    local pane_path="$SESSION_NAME:grid.$pane_index"

    tmux select-pane -t "$pane_path" -T "$title"

    tmux send-keys -t "$pane_path" "clear" C-m
    tmux send-keys -t "$pane_path" "printf '\\033[1;34m[%s]\\033[0m\\n' $(shell_quote "$title")" C-m
    tmux send-keys -t "$pane_path" "printf \"\033[2mTask: %s\033[0m\n\" $(shell_quote "$TASK")" C-m
    tmux send-keys -t "$pane_path" "echo" C-m

    if [ -n "$DEMO_DONE_DIR" ] && [ "$tool" != "title" ]; then
        local done_file="${DEMO_DONE_DIR}/${pane_index}-${tool}.done"
        launch_cmd="${launch_cmd}; __harbor_demo_status=\$?; printf '\\n\\033[2mDone (exit %s)\\033[0m\\n' \"\$__harbor_demo_status\"; touch $(shell_quote "$done_file")"
    fi

    tmux send-keys -t "$pane_path" "$launch_cmd" C-m
}

# Launch the selected assistants in the grid. A short stagger between panes
# avoids thundering-herd docker compose up calls.
launch_grid() {
    local i
    local total=${#SELECTED_TOOLS[@]}
    for i in "${!SELECTED_TOOLS[@]}"; do
        local tool="${SELECTED_TOOLS[$i]}"
        setup_pane "$i" "$tool" "${TOOL_TITLE[$tool]}" "$(build_pane_command "$tool")"
        if [ -n "$WORKFLOW" ] && [ "$i" -lt "$((total - 1))" ]; then
            sleep 8
        fi
    done
}

# Start a background watcher that ends the demo when all panes finish, or when
# the DURATION cap expires. Assistant panes write completion markers because
# their shell stays open after the agent command returns.
start_completion_watcher() {
    if [ "$DURATION" -le 0 ]; then
        return 0
    fi

    DEMO_WATCHER_RESULT=$(mktemp /tmp/harbor-launch-grid-watcher-XXXXXX)
    (
        local elapsed=0
        # Give the panes a moment to start before polling.
        sleep 2
        elapsed=$((elapsed + 2))

        while [ "$elapsed" -lt "$DURATION" ]; do
            local completed
            completed=$(find "$DEMO_DONE_DIR" -name '*.done' -type f 2>/dev/null | wc -l | tr -d '[:space:]')
            if [ "$completed" -ge "$DEMO_ASSISTANT_COUNT" ]; then
                echo "completed" > "$DEMO_WATCHER_RESULT"
                break
            fi
            sleep 1
            elapsed=$((elapsed + 1))
        done

        if [ "$elapsed" -ge "$DURATION" ]; then
            echo "timeout" > "$DEMO_WATCHER_RESULT"
        fi

        tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
    ) &
    DEMO_TIMER_PID=$!
}

# Main flow.
if [ -z "${HARBOR_DEMO_TASK+x}" ]; then
    TASK=$(default_task_for_workflow)
fi
parse_toolset "$TOOLS"
prepare_environment
if [ "$DURATION" -gt 0 ]; then
    DEMO_DONE_DIR=$(mktemp -d /tmp/harbor-launch-grid-done-XXXXXX)
fi
setup_tmux
launch_grid

banner "Attaching to tmux session: ${SESSION_NAME}"
if [ "$AUTO_PROMPT" = true ]; then
    info "The task is already running in each pane that supports auto-prompt."
else
    info "Type the task into each pane to compare the answers."
fi
if [ -n "$WORKFLOW" ]; then
    info "Watch how each coding assistant harness applies the ${WORKFLOW} workflow to the same prompt."
else
    info "Watch how the same backend and model behave across different coding assistants."
fi
if [[ " ${SELECTED_TOOLS[*]} " == *" title "* ]]; then
    info "The intro pane shows the backend, model, and workflow for the viewer."
fi

if [ "$DURATION" -gt 0 ]; then
    start_completion_watcher
    info "Autonomous mode: the demo will exit when all agents finish, or after ${DURATION} seconds."
else
    info "Detach from tmux by pressing Ctrl+b, then d. Close the terminal to end the demo."
fi
info "To stop the Harbor services later, run: harbor down"
echo

# Attach to tmux. The attach exits normally when the user detaches, or with a
# non-zero status when the background watcher kills the session. The || true
# keeps the script alive so the "Demo complete" message can be printed.
tmux attach-session -t "$SESSION_NAME" || true

if [ "$DURATION" -gt 0 ]; then
    # Wait for the background watcher to finish cleaning up the session.
    wait "$DEMO_TIMER_PID" 2>/dev/null || true

    watcher_result=$(cat "$DEMO_WATCHER_RESULT" 2>/dev/null || echo "timeout")
    rm -f "$DEMO_WATCHER_RESULT" 2>/dev/null || true
    rm -rf "$DEMO_DONE_DIR" 2>/dev/null || true

    banner "Demo complete"
    if [ "$watcher_result" = "completed" ]; then
        info "All agents finished; the demo has moved on."
    else
        info "The demo reached the ${DURATION}-second cap."
    fi
fi
