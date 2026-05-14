import os
import sys
import json
from functools import wraps


def _backend_provider():
    provider = os.environ.get("NPCSH_CHAT_PROVIDER", "ollama")
    if provider == "openai-like":
        return "openai"
    return provider


def _backend_model():
    model = os.environ.get("NPCSH_CHAT_MODEL", "qwen3.5:4b")
    if os.environ.get("NPCSH_CHAT_PROVIDER") == "openai-like" and not model.startswith("openai/"):
        return f"openai/{model}"
    return model


def _cors_origins():
    cors = os.environ.get("NPCSH_CORS", "*").strip()
    if cors in ("", "*"):
        return ["*"]
    return [origin.strip() for origin in cors.split(",") if origin.strip()]


def main():
    db_path = os.path.expanduser(os.environ.get("NPCSH_DB_PATH", "/data/npcsh_history.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    try:
        from npcsh._state import initialize_base_npcs_if_needed, setup_shell

        initialize_base_npcs_if_needed(db_path)
        _command_history, team, _default_npc = setup_shell()
    except Exception as exc:
        print(f"failed to initialize npcsh team: {exc}", file=sys.stderr)
        raise

    if team is None:
        raise RuntimeError("npcsh did not load an NPC team")

    try:
        from flask import request
        from npcpy import serve as serve_module
        from npcpy.serve import start_flask_server
    except Exception as exc:
        print(f"failed to import npcpy.serve.start_flask_server: {exc}", file=sys.stderr)
        raise

    port = int(os.environ.get("NPCSH_PORT", "5337"))
    original_chat = serve_module.app.view_functions.get("openai_chat_completions")
    npc_names = set(team.npcs.keys())
    if original_chat:
        @wraps(original_chat)
        def frontend_compatible_chat():
            data = request.get_json(silent=True) or {}
            selected_model = data.get("model")
            if selected_model in npc_names and not data.get("agent") and not data.get("npc"):
                patched = dict(data)
                patched["agent"] = selected_model
                patched["model"] = _backend_model()
                patched["provider"] = _backend_provider()
                request._cached_json = (patched, patched)
                request._cached_data = json.dumps(patched).encode("utf-8")
            return original_chat()

        serve_module.app.view_functions["openai_chat_completions"] = frontend_compatible_chat

    start_flask_server(
        port=port,
        cors_origins=_cors_origins(),
        teams={"main": team},
        npcs=team.npcs,
        db_path=db_path,
        user_npc_directory=os.path.expanduser("~/.npcsh/npc_team"),
    )


if __name__ == "__main__":
    main()
