"""Question worker: QuestionJob -> a reply in the Slack thread (Slice 7b, D-017).

retrieve and answer are injected callables; `bind` builds the real ones. Failed records
are reported individually so SQS redelivers only those (D-004). Question, answer and note
text are never logged.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from slackkb import qa
from slackkb import retrieve as retrieve_mod
from slackkb.config import Settings
from slackkb.models import QuestionJob
from slackkb.okf_note import OkfNote
from slackkb.qa import QaError, QaResult
from slackkb.slack_api import SlackClient, make_urllib_transport

logger = logging.getLogger(__name__)

SLACK_TIMEOUT_SECONDS = 10.0

QA_ERROR_TEXT = "Sorry, I couldn't answer that. Please try again."

Retrieve = Callable[[str, str], list[OkfNote]]
Answer = Callable[[str, list[OkfNote]], QaResult]


def slack_client(settings: Settings) -> SlackClient:
    """The worker's Slack client: a 10 s timeout, unlike views.open's 2.5 s (D-017)."""
    return SlackClient(
        settings.slack_bot_token, make_urllib_transport(SLACK_TIMEOUT_SECONDS)
    )


def slack_escape(text: str) -> str:
    """Escape &, < and > so relayed text can't ping @channel or forge a link."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _reply_text(result: QaResult) -> str:
    text = slack_escape(result.answer)
    if result.cited_note_ids:
        text += "\n\nNotes: " + ", ".join(result.cited_note_ids)
    return text


def _process(
    record: Mapping[str, Any], retrieve: Retrieve, answer: Answer, slack: SlackClient
) -> bool:
    message_id = record["messageId"]
    try:
        job = QuestionJob.model_validate_json(record.get("body") or "")
    except ValidationError:
        logger.warning("unparsable question job, message_id=%s", message_id)
        return False
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
            slack.chat_post_message(job.channel, job.thread_ts, _reply_text(result))
    except Exception as exc:
        logger.warning("question failed, %s, event_id=%s", type(exc).__name__, job.event_id)
        return False
    logger.info("question answered, event_id=%s notes=%d", job.event_id, len(notes))
    return True


def handle(
    event: Mapping[str, Any], *, retrieve: Retrieve, answer: Answer, slack: SlackClient
) -> dict:
    """Handle one SQS Lambda event; return the partial batch response."""
    failures = [
        {"itemIdentifier": record["messageId"]}
        for record in event.get("Records") or []
        if not _process(record, retrieve, answer, slack)
    ]
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
