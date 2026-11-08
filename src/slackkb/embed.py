"""The only module that calls Bedrock invoke_model for embeddings (Slice 6, D-002, D-008)."""

import json
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

DIMENSIONS = 512


class EmbedError(Exception):
    """The embedding call failed or returned something unusable."""


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
        embedding = json.loads(raw)["embedding"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EmbedError("response body is not a valid embedding payload") from exc
    if (
        not isinstance(embedding, list)
        or len(embedding) != DIMENSIONS
        or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in embedding
        )
    ):
        raise EmbedError(f"embedding is not {DIMENSIONS} numbers")
    return [float(x) for x in embedding]
