import json
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import BotoCoreError, ClientError

from slackkb.models import QuestionJob
from slackkb.queue import EnqueueError, send_question_job


def _job():
    return QuestionJob(
        event_id="Ev000TEST0001",
        team_id="T000TEST",
        channel="C000TEST",
        user="U000TEST",
        thread_ts="1762600000.000100",
        question="how do we rotate the signing secret?",
    )


def test_send_question_job_body(question_queue):
    sqs = boto3.client("sqs")
    send_question_job(sqs, question_queue.url, _job())
    messages = sqs.receive_message(QueueUrl=question_queue.url, MaxNumberOfMessages=10)[
        "Messages"
    ]
    assert len(messages) == 1
    assert json.loads(messages[0]["Body"]) == {
        "event_id": "Ev000TEST0001",
        "team_id": "T000TEST",
        "channel": "C000TEST",
        "user": "U000TEST",
        "thread_ts": "1762600000.000100",
        "question": "how do we rotate the signing secret?",
    }


@pytest.mark.parametrize(
    "exc",
    [
        ClientError({"Error": {"Code": "AccessDenied", "Message": "secret-detail"}}, "SendMessage"),
        BotoCoreError(),
    ],
)
def test_send_question_job_wraps_errors(exc):
    sqs = MagicMock()
    sqs.send_message.side_effect = exc
    with pytest.raises(EnqueueError) as info:
        send_question_job(sqs, "https://example/q", _job())
    assert info.value.__cause__ is exc
    assert "secret-detail" not in str(info.value)
