"""SQS access for capture jobs. The only module that talks to SQS.

The caller passes the boto3 SQS client in; nothing is created at import time.
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from slackkb.models import CaptureJob, QuestionJob


class EnqueueError(Exception):
    """The job was not sent. The message names only the botocore error class."""


def send_capture_job(sqs: Any, queue_url: str, job: CaptureJob) -> None:
    """Send one job; raise EnqueueError on botocore ClientError / BotoCoreError."""
    try:
        sqs.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())
    except (ClientError, BotoCoreError) as exc:
        raise EnqueueError(type(exc).__name__) from exc


def send_question_job(sqs: Any, queue_url: str, job: QuestionJob) -> None:
    """Send one question job; raise EnqueueError on botocore ClientError / BotoCoreError."""
    try:
        sqs.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())
    except (ClientError, BotoCoreError) as exc:
        raise EnqueueError(type(exc).__name__) from exc
