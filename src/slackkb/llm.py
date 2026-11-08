"""Bedrock Converse calls (D-002, D-016). The only module that calls Bedrock."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError


class LlmError(RuntimeError):
    """Bedrock failed or did not return the forced tool call."""


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
        )
    except (ClientError, BotoCoreError) as exc:
        raise LlmError(f"bedrock call failed: {type(exc).__name__}") from exc
    content = response.get("output", {}).get("message", {}).get("content", [])
    for block in content:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise LlmError("response had no toolUse block")
