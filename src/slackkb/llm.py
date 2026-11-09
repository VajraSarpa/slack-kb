"""Bedrock Converse calls (D-002, D-016). The only module that calls Bedrock."""

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

MAX_TOKENS = 1024  # D-012 output cap


class LlmError(RuntimeError):
    """Bedrock failed or did not return the forced tool call."""


def _count(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _log_usage(model_id: str, usage: Any) -> None:
    """One INFO line with token counts (D-019); a WARNING if either count is unusable."""
    input_tokens = _count(usage, "inputTokens")
    output_tokens = _count(usage, "outputTokens")
    if input_tokens is None or output_tokens is None:
        log.warning("bedrock usage missing, call=converse model_id=%s", model_id)
        return
    log.info(
        "bedrock usage, call=converse model_id=%s input_tokens=%d output_tokens=%d",
        model_id,
        input_tokens,
        output_tokens,
    )


def ask(client: Any, *, model_id: str, system: str, user: str, tool: dict) -> dict:
    """Call Converse with one forced tool and return that tool's input dict."""
    try:
        response = client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            toolConfig={
                "tools": [tool],
                "toolChoice": {"tool": {"name": tool["toolSpec"]["name"]}},
            },
            inferenceConfig={"maxTokens": MAX_TOKENS},
        )
    except (ClientError, BotoCoreError) as exc:
        raise LlmError(f"bedrock call failed: {type(exc).__name__}") from exc
    _log_usage(model_id, response.get("usage"))
    if response.get("stopReason") == "max_tokens":
        log.warning("bedrock stopped on max_tokens, call=converse model_id=%s", model_id)
        raise LlmError("response stopped on max_tokens")
    content = response.get("output", {}).get("message", {}).get("content", [])
    for block in content:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise LlmError("response had no toolUse block")
