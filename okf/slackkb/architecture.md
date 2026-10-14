# SlackKB target architecture

- Entry: Slack -> API Gateway -> capture Lambda. Verify signature, ack within 3 s,
  write the note with status CAPTURED, enqueue to SQS.
- Worker Lambda consumes SQS: structure with Bedrock, write OKF note to S3
  (canonical), update DynamoDB metadata, reply in Slack.
- Q&A: thread reply -> retrieve notes -> Bedrock answer citing note_ids.
- Boundaries: store.py (DynamoDB), blob.py (S3), llm.py (Bedrock),
  slack_api.py (Slack Web API). Handlers never import boto3.
- Failure: SQS redrive to DLQ; the user always gets an ephemeral message.
- Secrets: Secrets Manager in AWS; pydantic-settings locally and in tests.
