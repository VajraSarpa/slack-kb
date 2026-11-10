"""Question worker: QuestionJob -> a reply in the Slack thread (Slice 7b, D-017).

retrieve and answer are injected callables; `bind` builds the real ones. Failed records
are reported individually so SQS redelivers only those (D-004). Question, answer and note
text are never logged.
"""

import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from slackkb import obs, qa, store
from slackkb import retrieve as retrieve_mod
from slackkb.config import Settings
from slackkb.models import QuestionJob
from slackkb.okf_note import OkfNote
from slackkb.qa import QaError, QaResult
from slackkb.slack_api import SlackClient, make_urllib_transport

logger = logging.getLogger(__name__)

SLACK_TIMEOUT_SECONDS = 10.0

QA_ERROR_TEXT = "Sorry, I couldn't answer that. Please try again."

SAVED_NOTE = "a saved note"

_CHANNEL_ID = re.compile(r"[A-Z0-9]+")

Retrieve = Callable[[str, str], list[OkfNote]]
Answer = Callable[[str, list[OkfNote]], QaResult]
SeverityOf = Callable[[str], str | None]


def slack_client(settings: Settings) -> SlackClient:
    """The worker's Slack client: a 10 s timeout, unlike views.open's 2.5 s (D-017)."""
    return SlackClient(
        settings.require("slack_bot_token"), make_urllib_transport(SLACK_TIMEOUT_SECONDS)
    )


def slack_escape(text: str) -> str:
    """Escape &, < and > so relayed text can't ping @channel or forge a link."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _when(created_at: str) -> str:
    try:
        moment = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moment = moment.astimezone(UTC)
        stamp = int(moment.timestamp())
    except (ValueError, OverflowError):
        return slack_escape(created_at)
    return (
        f"<!date^{stamp}^{{date_short_pretty}} {{time}}"
        f"|{moment:%Y-%m-%d %H:%M} UTC>"
    )


def severity_lookup(table: Any) -> Callable[[str], str | None]:
    """note_id -> the stored note's severity name, or None when the note is gone."""

    def lookup(note_id: str) -> str | None:
        note = store.get_note(table, note_id)
        return None if note is None else note.severity.value

    return lookup


def _severity_part(note_id: str, severity_of: SeverityOf | None) -> str:
    if severity_of is None:
        return ""
    try:
        severity = severity_of(note_id)
    except Exception:
        severity = None
    if severity is None:
        logger.warning("severity unavailable, note_id=%s", note_id)
        return ""
    return " · " + slack_escape(severity)


def _redact_note_ids(answer: str, notes: list[OkfNote]) -> str:
    """Replace each given note's id, as a whole token, with "a saved note" (D-021)."""
    ids = sorted({n.note_id for n in notes if n.note_id}, key=len, reverse=True)
    if not ids:
        return answer
    pattern = re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(i) for i in ids) + r")(?![\w-])"
    )
    seen: list[str] = []

    def swap(match: re.Match[str]) -> str:
        if match.group(1) not in seen:
            seen.append(match.group(1))
        return SAVED_NOTE

    redacted = pattern.sub(swap, answer)
    for note_id in seen:
        logger.warning("note id in answer, note_id=%s", note_id)
    return redacted


def _reply_text(
    result: QaResult, notes: list[OkfNote], severity_of: SeverityOf | None = None
) -> str:
    text = slack_escape(_redact_note_ids(result.answer, notes))
    if result.cited_note_ids:
        by_id = {note.note_id: note for note in notes}
        text += "\n\nNotes:"
        for note_id in result.cited_note_ids:
            note = by_id.get(note_id)
            if note is None:
                text += "\n• " + slack_escape(note_id)
                continue
            text += "\n• " + _when(note.created_at)
            if _CHANNEL_ID.fullmatch(note.channel_id):
                text += f" in <#{note.channel_id}>"
            text += _severity_part(note_id, severity_of)
    return text


def _process(
    record: Mapping[str, Any],
    retrieve: Retrieve,
    answer: Answer,
    slack: SlackClient,
    severity_of: SeverityOf | None = None,
) -> bool:
    message_id = record["messageId"]
    try:
        job = QuestionJob.model_validate_json(record.get("body") or "")
    except ValidationError:
        logger.warning("unparsable question job, message_id=%s", message_id)
        return False
    obs.bind(job.event_id)
    try:
        notes = retrieve(job.question, job.team_id)
        if not notes:
            text = 'No notes match "' + slack_escape(job.question) + '".'
            slack.chat_post_message(job.channel, job.thread_ts, text)
        else:
            try:
                result = answer(job.question, notes)
            except QaError:
                logger.warning("question not answered, event_id=%s", job.event_id)
                slack.chat_post_ephemeral(job.channel, job.user, job.thread_ts, QA_ERROR_TEXT)
                return True
            text = _reply_text(result, notes, severity_of)
            slack.chat_post_message(job.channel, job.thread_ts, text)
    except Exception as exc:
        logger.warning("question failed, %s, event_id=%s", type(exc).__name__, job.event_id)
        return False
    logger.info("question answered, event_id=%s notes=%d", job.event_id, len(notes))
    return True


def handle(
    event: Mapping[str, Any],
    *,
    retrieve: Retrieve,
    answer: Answer,
    slack: SlackClient,
    severity_of: SeverityOf | None = None,
) -> dict:
    """Handle one SQS Lambda event; return the partial batch response."""
    failures = []
    for record in event.get("Records") or []:
        with obs.trace():
            ok = _process(record, retrieve, answer, slack, severity_of)
        if not ok:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def bind(
    settings: Settings, *, bedrock: Any, vectors_table: Any, bucket: Any
) -> tuple[Retrieve, Answer]:
    """The real retrieve and answer callables for handle."""

    def retrieve(question: str, team_id: str) -> list[OkfNote]:
        return retrieve_mod.retrieve(
            question,
            team_id,
            client=bedrock,
            model_id=settings.embed_model_id,
            vectors_table=vectors_table,
            bucket=bucket,
        )

    def answer(question: str, notes: list[OkfNote]) -> QaResult:
        return qa.answer_question(
            question, notes, client=bedrock, model_id=settings.qa_model_id
        )

    return retrieve, answer
