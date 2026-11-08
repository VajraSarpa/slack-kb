"""The only module that calls Bedrock invoke_model for embeddings (Slice 6, D-002, D-008)."""

import json
import logging
import math
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

DIMENSIONS = 512
FLOAT32_MAX = 3.4028234663852886e38


log = logging.getLogger(__name__)


class EmbedError(Exception):
    """The embedding call failed or returned something unusable."""


def _log_usage(model_id: str, count: Any) -> None:
    """One INFO line with the input token count (D-019); a WARNING if it is unusable."""
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        log.info("bedrock usage, call=embed model_id=%s input_tokens=%d", model_id, count)
    else:
        log.warning("bedrock usage missing, call=embed model_id=%s", model_id)


def embed_text(client: Any, *, model_id: str, text: str) -> list[float]:
    """Embed text with Titan Text Embeddings V2: 512 dimensions, normalised."""
    try:
        resp = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}),
        )
        raw = resp["body"].read()
    except (ClientError, BotoCoreError) as exc:
        raise EmbedError(type(exc).__name__) from exc
    try:
        body = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise EmbedError("response body is not a valid embedding payload") from exc
    if isinstance(body, dict):
        _log_usage(model_id, body.get("inputTextTokenCount"))
    try:
        embedding = body["embedding"]
    except (KeyError, TypeError) as exc:
        raise EmbedError("response body is not a valid embedding payload") from exc
    if (
        not isinstance(embedding, list)
        or len(embedding) != DIMENSIONS
        or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in embedding
        )
    ):
        raise EmbedError(f"embedding is not {DIMENSIONS} numbers")
    try:
        out = [float(x) for x in embedding]
    except (OverflowError, ValueError) as exc:
        raise EmbedError("embedding holds a number that is not a float") from exc
    if not all(math.isfinite(x) and abs(x) <= FLOAT32_MAX for x in out):
        raise EmbedError("embedding holds a value that is not a finite float32")
    return out
