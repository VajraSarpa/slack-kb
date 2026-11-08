# Decisions

- D-001 Fresh repo; tutorial code is read-only reference.
- D-002 Bedrock via llm.py; no direct Anthropic API.
- D-003 Capture via /bnote slash command. #log message capture deferred.
- D-004 Async processing via SQS with redrive DLQ.
- D-005 infra/ (SAM, IAM) is human-authored; agent may write tests for it.
- D-006 note_id = sha256(team_id:trigger_id), first 32 hex chars. Slash commands
        are not retried by Slack; the conditional put still blocks duplicates.
- D-007 Signing secret from pydantic-settings; Secrets Manager wiring in Slice 8.
- D-008 (2026-11-07) Retrieval store for Slice 6: DynamoDB, similarity in
        Lambda. Chosen on cost: OpenSearch Serverless (Knowledge Bases) has
        a ~$175/month floor; S3 Vectors is cheap but moto can't run its
        QueryVectors, so retrieval would only be Stubber-tested; Aurora
        pgvector needs a VPC. Vectors live in their own table note_vectors
        (partition key team_id, sort key note_id; the vector as packed
        float32 bytes), not in the notes table. Embeddings: Titan Text
        Embeddings V2 via Bedrock through embed.py (D-002), 512 dimensions,
        normalised, so similarity is a dot product; the model id and table
        name are Settings fields. Only the note text is embedded, never
        frontmatter. The worker writes S3, then the vector, then moves the
        note to ROUTED; an embedding or vector-write failure raises, so SQS
        retries and the DLQ applies; the vector put is an idempotent
        overwrite. retrieve(question, team_id) embeds the question, reads
        that team's partition, ranks by dot product and returns the top k
        note_ids; text comes from S3 (blob.get_note). No match -> a "no
        results" answer that names the query it ran. Limit, written down:
        move to S3 Vectors when a team passes ~5,000 notes or retrieval
        p95 exceeds 1 s; only retrieve.py and the worker's vector write
        change. The table is Vajra's to add in infra/ (Slice 8).
- D-009 Note status: CAPTURED -> ROUTED, or FAILED after the DLQ.
        capture writes CAPTURED. The worker sets ROUTED when it finishes
        (Slice 2); the DLQ handler sets FAILED (Slice 2b). Each move is a
        conditional update from CAPTURED only, so a repeat SQS delivery
        can't move a note backward or out of FAILED.
- D-010 The error path is its own slice (2b), not part of Slice 2: when a note
        goes FAILED after the DLQ, the user who ran /bnote gets an ephemeral
        message via response_url (30-min window; no bot token). The capture
        handler still never calls response_url; only the 2b path does.
- D-011 Events API retries (Slice 7) are deduplicated, not dropped. Key is
        Slack's event_id (same on every retry). Verify the signature first,
        then claim the key with a conditional put, then enqueue to SQS.
        Key already claimed -> 200, no work. Enqueue fails -> delete the
        claim and return 500, so Slack's retry is a real recovery (A0 #2).
        Keys live in their own DynamoDB table with a 1-hour TTL, not the
        notes table: they aren't notes, and Slack's retries end within
        minutes. The table is Vajra's to add in infra/ (Slice 8).
- D-012 Q&A model (Slice 5): Claude Haiku 5.5 on Bedrock, called through a
        cross-region inference profile (us. prefix). The model ID is a
        pydantic-settings field, never hard-coded in llm.py. IAM allows
        bedrock:InvokeModel on exactly two ARNs: the inference profile
        (arn:aws:bedrock:<region>:<account>:inference-profile/us.anthropic.<id>)
        and the foundation model it routes to
        (arn:aws:bedrock:*::foundation-model/anthropic.<id>). The tutorial's
        ARN (cicd-spec.md:164) mixes the two forms and is not reused.
        Exact <id> is unverified: look it up with the slackkb-dev SSO
        profile before Slice 8.
- D-013 Severity modal (Slice 3) opens from a "Set severity" button in the
        /bnote ack, not from capture. The button's block_actions payload
        carries a fresh trigger_id; modal.py verifies the signature, calls
        views.open through slack_api.py, then handles view_submission.
        note_id travels in the view's private_metadata. A severity outside
        the OKF enum returns response_action "errors" and changes nothing.
        Severity is a plain update on an existing note; it does not touch
        status (D-009). capture.py still makes no Slack Web API calls.
        views.open needs a bot token (xoxb-): a new required Settings
        field, wired to Secrets Manager in Slice 8.
- D-014 OKF note in S3 (Slice 4). S3 holds a note's content; DynamoDB
        holds its mutable state. Object key notes/<team_id>/<note_id>.md:
        YAML frontmatter between "---" lines, then the note text as the
        body. Frontmatter carries only fields that never change: note_id,
        team_id, channel_id, user_id, created_at. Severity and status stay
        in DynamoDB only, so the modal (D-013) and status moves (D-009)
        never touch S3 and nothing drifts. Readers that need severity join
        on note_id. Frontmatter is written with yaml.safe_dump and read
        with yaml.safe_load (pyyaml is a direct dependency); note text is
        never put in frontmatter, and a body containing "---" or YAML-like
        lines must round-trip unchanged. The worker writes S3 first, then
        moves CAPTURED -> ROUTED; the put is an idempotent overwrite, and
        an S3 failure raises so SQS retries and the DLQ applies. All S3
        access goes through blob.py; the bucket name is a Settings field.
        Amended 2026-11-07: the worker's CAPTURED -> ROUTED update also
        removes text from the DynamoDB item (same conditional update), so
        S3 holds the only copy of a routed note's content; readers get text
        from S3. A redelivered ROUTED note is done: nothing is rewritten.
        A FAILED note keeps its text (it never reached S3).
- D-015 (2026-11-04, confirmed by Vajra) A failed
        enqueue leaves no note behind. Found by the Sārathi C11 run: when
        capture writes CAPTURED and the SQS send fails, the user gets the
        retry message but the note stays CAPTURED forever with no job.
        D-006 means Slack never retries a slash command, and the user's own
        retry has a new trigger_id, so a new note_id; nothing ever
        processes the old note. Rule, mirroring D-011: on an enqueue
        failure, capture deletes the note with a conditional delete (only
        while status is CAPTURED), logs the note_id, and returns the retry
        message. If the delete fails too, log it and still return the
        retry message. The duplicate path is unchanged (a duplicate still
        sends nothing; Slice 2 req 2). Rejected: re-sending on a duplicate
        (no duplicate ever arrives for a slash command), and a sweeper
        (more moving parts for a rare failure). Needs store.delete_if_captured
        and a test that a failed send leaves no item.
- D-016 (2026-11-07) Q&A (Slice 5). llm.py calls the Bedrock Converse
        API through an injected bedrock-runtime client and forces one tool,
        "answer", whose input is {answer: str, cited_note_ids: [str]}; no
        free-text parsing. Converse is authorised by bedrock:InvokeModel, so
        D-012's IAM stands. Tests fake Bedrock with botocore's Stubber on a
        real client (offline, schema-checked); no conftest fake. Untrusted
        text: the system prompt is a fixed constant; the question and each
        note go in the user message, each note in <note id="..."> ...
        </note> with &, <, > escaped so a note can't close its block; no
        .replace()/.format() over user text (A0 #4). qa.answer_question
        (question, notes, *, client, model_id) -> QaResult: no notes ->
        fixed "No notes match." and no Bedrock call; a cited id not among
        the notes given is dropped; only the count of dropped ids is
        logged, never an id (model output; it can carry note text).
        Bedrock ClientError /
        BotoCoreError, or tool output that doesn't validate, raises QaError;
        qa makes no Slack calls (Slice 7 turns QaError into the ephemeral
        message). Question and note text are never logged. Settings gains a
        required qa_model_id (SLACKKB_QA_MODEL_ID), no default (D-012).
