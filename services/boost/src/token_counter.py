"""Local token counting for Anthropic-compatible count_tokens endpoint.

Uses tiktoken with the cl100k_base encoding (used by GPT-4/Claude-class
models) to estimate input token counts without making a backend inference
call.  The count includes per-message framing overhead that chat APIs add.

When tiktoken is unavailable (e.g. missing native extension), falls back
to a chars/4 heuristic which is a reasonable approximation for English text.
"""

import json
import log

logger = log.setup_logger(__name__)

# Per-message and per-name overhead tokens for chat-format APIs.
# These values match the OpenAI tiktoken cookbook for gpt-4 / cl100k_base.
_TOKENS_PER_MESSAGE = 3
_TOKENS_PER_NAME = 1
_TOKENS_REPLY_PRIMER = 3  # every reply is primed with <|start|>assistant<|message|>

try:
    import tiktoken
    _encoding = tiktoken.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except Exception:
    _encoding = None
    _USE_TIKTOKEN = False
    logger.warning("tiktoken unavailable; count_tokens will use chars/4 heuristic")


def _tiktoken_len(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(_encoding.encode(text))


def _heuristic_len(text: str) -> int:
    """Approximate token count: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def _token_len(text: str) -> int:
    if _USE_TIKTOKEN:
        return _tiktoken_len(text)
    return _heuristic_len(text)


def _count_tool_tokens(tools: list) -> int:
    """Estimate tokens consumed by tool/function definitions.

    Tool definitions are serialized into the system prompt area by most
    backends.  We count the JSON representation of each tool's schema
    plus a small fixed overhead per tool for framing.
    """
    if not tools:
        return 0

    total = 0
    for tool in tools:
        # Each tool definition has name, description, parameters
        func = tool.get("function", tool)
        parts = []

        name = func.get("name", "")
        if name:
            parts.append(name)

        desc = func.get("description", "")
        if desc:
            parts.append(desc)

        params = func.get("parameters") or func.get("input_schema")
        if params:
            parts.append(json.dumps(params, separators=(",", ":")))

        tool_text = "\n".join(parts)
        total += _token_len(tool_text) + _TOKENS_PER_MESSAGE
    return total


def count_messages_tokens(openai_messages: list, tools: list | None = None) -> int:
    """Count tokens for a list of OpenAI-format messages and optional tools.

    Args:
        openai_messages: Messages in OpenAI chat format (already converted
            from Anthropic format by ``_convert_messages``).
        tools: Optional list of tool definitions in OpenAI function-calling
            format (already converted by ``_convert_tools``).

    Returns:
        Estimated input token count.
    """
    total = 0

    for msg in openai_messages:
        total += _TOKENS_PER_MESSAGE

        role = msg.get("role", "")
        total += _token_len(role)

        content = msg.get("content")
        if isinstance(content, str):
            total += _token_len(content)
        elif isinstance(content, list):
            # Multimodal content array
            for part in content:
                if isinstance(part, dict):
                    part_type = part.get("type", "")
                    if part_type == "text":
                        total += _token_len(part.get("text", ""))
                    elif part_type == "image_url":
                        # Images consume a fixed token budget; 85 is the
                        # low-detail estimate used by OpenAI.
                        total += 85
                    else:
                        # Unknown part type -- count any text-like field
                        text = part.get("text", "")
                        if text:
                            total += _token_len(text)

        # Tool call content in assistant messages
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", "")
                total += _token_len(name) + _token_len(args)

        name = msg.get("name")
        if name:
            total += _token_len(name) + _TOKENS_PER_NAME

    total += _TOKENS_REPLY_PRIMER

    # Tool definitions
    if tools:
        total += _count_tool_tokens(tools)

    return total
