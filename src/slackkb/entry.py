"""Lambda entry points (D-020): one handler per function.

Importing this module makes no AWS or network call. On a container's first call a
handler fetches only the secrets its Lambda uses, builds Settings and its clients, and
caches them; later calls reuse them. A failed cold start caches nothing.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3

from slackkb import capture, events, modal, notify, obs, thread, worker
from slackkb.config import Settings
from slackkb.embed import embed_text
from slackkb.slack_api import SlackClient, make_response_url_transport, post_response_url

NOTIFY_POST_TIMEOUT_SECONDS = 10.0

_obs_configured = False
_cache: dict[str, Any] = {}


@dataclass(frozen=True)
class _Secrets:
    signing: bool = False
    bot_token: bool = False


def _session() -> Any:
    return boto3.session.Session()


def reset() -> None:
    """Clear every cache (for tests)."""
    global _obs_configured
    _obs_configured = False
    _cache.clear()


def _configure_obs() -> None:
    global _obs_configured
    if not _obs_configured:
        obs.configure()
        _obs_configured = True


def _fetch_secret(session: Any, env_var: str) -> str | None:
    arn = os.environ.get(env_var)
    if not arn:
        return None
    client = session.client("secretsmanager")
    return client.get_secret_value(SecretId=arn)["SecretString"]


def _settings(session: Any, secrets: _Secrets) -> Settings:
    signing = _fetch_secret(session, "SIGNING_SECRET_ARN") if secrets.signing else None
    token = _fetch_secret(session, "SLACK_BOT_TOKEN_ARN") if secrets.bot_token else None
    return Settings(signing_secret=signing, slack_bot_token=token)  # type: ignore[call-arg]


def _cold_start(name: str, secrets: _Secrets, build: Callable[[Any, Settings], dict]) -> dict:
    cached = _cache.get(name)
    if cached is None:
        _configure_obs()
        session = _session()
        settings = _settings(session, secrets)
        cached = build(session, settings)
        cached["settings"] = settings
        _cache[name] = cached
    return cached


def _now() -> int:
    return int(time.time())


def _table(session: Any, name: str) -> Any:
    return session.resource("dynamodb").Table(name)


def _bucket(session: Any, name: str) -> Any:
    return session.resource("s3").Bucket(name)


def capture_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        return {
            "table": _table(session, settings.notes_table),
            "sqs": session.client("sqs"),
        }

    state = _cold_start("capture", _Secrets(signing=True), build)
    return capture.handle(
        event, table=state["table"], sqs=state["sqs"], settings=state["settings"], now=_now()
    )


def modal_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        return {
            "table": _table(session, settings.notes_table),
            "slack": SlackClient(settings.require("slack_bot_token")),
        }

    state = _cold_start("modal", _Secrets(signing=True, bot_token=True), build)
    return modal.handle(
        event, table=state["table"], slack=state["slack"], settings=state["settings"], now=_now()
    )


def events_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        return {
            "events_table": _table(session, settings.events_table),
            "sqs": session.client("sqs"),
        }

    state = _cold_start("events", _Secrets(signing=True), build)
    return events.handle(
        event,
        events_table=state["events_table"],
        sqs=state["sqs"],
        settings=state["settings"],
        now=_now(),
    )


def worker_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        bedrock = session.client("bedrock-runtime")

        def embed(text: str) -> list[float]:
            return embed_text(bedrock, model_id=settings.embed_model_id, text=text)

        return {
            "table": _table(session, settings.notes_table),
            "bucket": _bucket(session, settings.notes_bucket),
            "vectors_table": _table(session, settings.vectors_table),
            "embed": embed,
        }

    state = _cold_start("worker", _Secrets(), build)
    return worker.handle(
        event,
        table=state["table"],
        bucket=state["bucket"],
        vectors_table=state["vectors_table"],
        embed=state["embed"],
    )


def notify_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        transport = make_response_url_transport(NOTIFY_POST_TIMEOUT_SECONDS)

        def post(url: str, text: str) -> None:
            post_response_url(url, text, transport)

        return {
            "table": _table(session, settings.notes_table),
            "bucket": _bucket(session, settings.notes_bucket),
            "vectors_table": _table(session, settings.vectors_table),
            "post": post,
        }

    state = _cold_start("notify", _Secrets(), build)
    return notify.handle(
        event,
        table=state["table"],
        bucket=state["bucket"],
        vectors_table=state["vectors_table"],
        post=state["post"],
    )


def thread_handler(event: Any, context: Any) -> Any:
    def build(session: Any, settings: Settings) -> dict:
        retrieve, answer = thread.bind(
            settings,
            bedrock=session.client("bedrock-runtime"),
            vectors_table=_table(session, settings.vectors_table),
            bucket=_bucket(session, settings.notes_bucket),
        )
        return {"retrieve": retrieve, "answer": answer, "slack": thread.slack_client(settings)}

    state = _cold_start("thread", _Secrets(bot_token=True), build)
    return thread.handle(
        event, retrieve=state["retrieve"], answer=state["answer"], slack=state["slack"]
    )
