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
        Amended 2026-11-12 (Vajra): retrieve returns up to k notes whose S3
        objects exist. A missing object is logged (WARNING, with its
        note_id) and skipped, and the next-ranked note takes its place, so
        a stale vector no longer costs the answer a note. It stops at k
        notes found or when the ranking runs out.
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
        Pinned 2026-11-09 (Slice 8d): us.anthropic.claude-haiku-5-5, listed
        by `aws bedrock list-inference-profiles` in us-east-2 with the
        slackkb-dev profile (an `aws login` profile on Vajra's IAM user,
        not SSO); the template's QaModelBaseId is anthropic.claude-haiku-5-5.
        The foundation-model ARN it routes to is checked with
        `aws bedrock get-inference-profile` before the first deploy.
        Output cap (2026-11-09, cost): every Converse call sets
        inferenceConfig maxTokens = 1024. A response that stops on
        max_tokens is an LlmError (logged), never a partial answer.
        Cost at dev volume ≈ $1/month (per call; $0 idle); the $175/month
        figure is OpenSearch Serverless, ruled out in D-008.
        Model changed 2026-11-09 (Vajra, at the first deploy): this AWS
        account is refused every Anthropic model ("not available for this
        account", agreementAvailability NOT_AVAILABLE for Haiku 5.5, 4.5 and
        3), so Q&A uses Amazon Nova 2 Lite: us.amazon.nova-2-lite-v1:0,
        QaModelBaseId amazon.nova-2-lite-v1:0 (routes to
        foundation-model/amazon.nova-2-lite-v1:0 in us-east-1/2, us-west-2;
        the region-* foundation-model ARN covers it). Checked by hand: one
        Converse call with the forced answer tool and maxTokens 1024 returned
        stopReason tool_use with answer + cited_note_ids. No code change;
        llm.py is model-agnostic. Anthropic can come back through an AWS
        access request, by changing QaModelBaseId only.
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
        never write to S3 and nothing drifts. Readers that need severity join
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
        A FAILED note keeps its text in DynamoDB, the only copy: notify
        deletes any S3 object (D-018).
        Amended 2026-11-10 (Vajra): "never write to S3" was "never touch
        S3", which read as no reads either. Any reader, the modal included,
        may read a note's text from S3 through blob.py. Nothing keeps a
        second copy of a routed note's text to save that read: no DynamoDB
        attribute, no other table, no cache that outlives the request. The
        note's own Slack messages may carry its text (e.g. the ack's "Set
        severity" button value), and the modal may show text from that
        payload: that copy is Slack's, not ours.
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
- D-017 (2026-11-08) Thread replies (Slice 7, split 7a/7b). The bot
        answers app_mention events only, never every message (Vajra): no
        per-message cost, no guessing what is a question (A0 #7). An event
        with a bot_id or a subtype is ignored, so the bot never answers
        itself. The question is the event text with every mention token
        (<@U...> or <@U...|name>) removed and whitespace stripped; an empty
        question gets no work. 7a, ingress (events.py), D-011 in order:
        verify the signature (url_verification is answered only after it,
        A0 #5), claim event_id in the events table (conditional put;
        expires_at = now + 3600 is the TTL attribute), then send a
        QuestionJob (event_id, team_id, channel, user, thread_ts, question)
        to its own SQS queue with its own DLQ (D-004), not the capture
        queue, and reply 200. thread_ts is the event's thread_ts, or its ts
        when the mention is top-level, so the reply always lands in a
        thread. 7b, the question worker (thread.py): retrieve (D-008), then
        answer_question (D-016), then chat.postMessage in the thread with
        the bot token (D-013): the answer, then the cited note_ids. No
        notes -> a reply that names the query it ran (D-008). QaError -> an
        ephemeral "couldn't answer" to the asking user in that thread
        (chat.postEphemeral; D-016) and the job is done, not retried. Any
        other failure (embedding, vector read, S3, a Slack post) is a batch
        item failure, so SQS retries and the DLQ applies. Text the bot
        echoes or relays (the query, the model's answer) has Slack's &, <, >
        escaped so it can't ping @channel or forge a link. Question text is
        never logged. The events table and question queue are Vajra's to add
        in infra/ (Slice 8).
        Amended 2026-11-08 (Vajra): the question worker is at-least-once.
        chat.postMessage has no idempotency key, so a redelivered job may
        post a second reply; that is accepted over losing one (A0 #1). The
        worker's Slack calls use a 10 s timeout (views.open keeps 2.5 s for
        the 3 s trigger_id), so a slow Slack reply doesn't turn a landed
        post into a retry. A worker-side "answered" marker waits for Slice 9
        logs to show repeat answers for one event_id.
- D-018 (2026-11-08) Failure notice (Slice 2b, D-010). response_url
        rides on the CaptureJob, not the note: it is a short-lived bearer
        URL, so it stays out of DynamoDB and S3 (D-014), and SQS moves the
        job body to the DLQ unchanged. CaptureRequest and CaptureJob gain
        an optional response_url that must start with https:// when
        present; capture copies it from the form onto the job and never
        calls it (D-010). Optional so a job without one still parses: the
        worker ignores the field, and notify logs that the user can't be
        told. notify.py handles the capture DLQ (an SQS batch handler like
        the worker): parse the job; move CAPTURED -> FAILED (D-009, the
        conditional update); a ROUTED note gets no notice; a FAILED note
        (repeat DLQ delivery) is handled again. A FAILED note keeps no S3
        object or vector (D-014): notify deletes both, because no worker
        delivery follows once the message is in the DLQ. Then it posts
        {"response_type": "ephemeral", "text": FAILED_TEXT} to the
        response_url through slack_api (no bot token, 10 s timeout as in
        the D-017 amendment; success is any 2xx status, the body is not
        read). The notice doesn't echo the note text. At-least-once: a
        redelivered DLQ job may post twice, as in D-017. A 4xx reply
        (expired or used-up URL; Slack allows 30 min) is permanent: logged,
        job done. A 5xx, a transport error, or a store/S3/vector error is a
        batch item failure, so SQS redelivers; once the 30 min pass the URL
        expires and the 4xx ends it. An unparsable job or a missing note is
        logged and done (there is no further queue). Never logged: the
        response_url, the note text. For Vajra in infra/ (Slice 8): the
        capture DLQ gets notify as its event source, and maxReceiveCount x
        the visibility timeout should land jobs in the DLQ well inside
        30 min, or the notice can't be delivered.
- D-019 (2026-11-08) Observability (Slice 9, split 9a/9b). Vajra picked
        the trace id; Claude wrote the rest under the standing delegation.
        stdlib logging only, no new dependency. New module obs.py:
        trace_id lives in a contextvar. A trace is the note_id on the
        capture path (capture, modal, worker, notify) and the event_id on
        the question path (events, thread), so one note or one question
        reads across Lambdas with no model change, and a Slack retry or an
        SQS redelivery shares its trace (repeat answers for one event_id
        show up, the D-017 "answered" marker question). Each HTTP handler
        call and each SQS record runs in its own trace, which starts as a
        random id ("r-" + 16 hex) and is rebound to the note_id/event_id
        once parsed; an id that isn't 1-64 of [A-Za-z0-9_-] is not bound
        (the random id stays), so request input never shapes the field.
        obs.configure() (called by the Lambda entry points, Slice 8)
        installs one stdout handler writing one JSON object per line with
        ts (UTC, ms, Z), level, logger, msg, trace_id, plus exc (the class
        name only) when exc_info is set; it sets the root level to INFO and
        botocore, boto3, urllib3 to WARNING (botocore DEBUG logs whole
        Bedrock requests, D-016 carry-over); calling it again doesn't add a
        second handler. Existing log messages keep their text. Token spend
        (9b): llm.ask and embed.embed_text each log one INFO line per
        successful Bedrock call with model_id and token counts (Converse
        usage inputTokens/outputTokens; Titan inputTextTokenCount), counts
        only, never prices, prompts or text; a response without counts
        logs a warning and the call still succeeds. Never logged, as
        before: note text, question text, response_url, tokens, secrets.
- D-020 (2026-11-08) Lambda entry points and secrets (Slice 8a; amends
        D-007). Vajra picked: secrets fetched by ARN at cold start, and
        both secrets optional in Settings, checked where used. Claude wrote
        the rest under the standing delegation. New module entry.py with
        six handlers, each (event, context) -> what handle() returns:
        capture_handler, modal_handler, events_handler, worker_handler,
        notify_handler, thread_handler; the template's Handler is
        slackkb.entry.<name>. Importing entry.py makes no AWS or network
        call. On a container's first call, cached for its life: run
        obs.configure(); fetch the secrets that Lambda uses with Secrets
        Manager GetSecretValue (the whole SecretString) from the ARN in
        SIGNING_SECRET_ARN / SLACK_BOT_TOKEN_ARN; build Settings() from the
        SLACKKB_ environment plus those values; build the boto3 DynamoDB
        Tables, S3 Bucket, SQS and bedrock-runtime clients it needs. A
        failed fetch raises, so the cold start fails and Lambda or SQS
        retries; nothing is cached on failure. Who reads which secret:
        capture and events the signing secret; modal both; thread the bot
        token; worker and notify none. Each call: now = int(time.time()),
        the event passed to handle() unchanged. Bindings: worker embed =
        embed_text on bedrock-runtime with embed_model_id; notify post =
        post_response_url with a 10 s response_url transport (D-018);
        thread uses thread.bind and thread.slack_client (10 s, D-017);
        modal's SlackClient keeps the 2.5 s views.open transport.
        Amendment to D-007: signing_secret and slack_bot_token become
        optional (None when unset), so a Lambda gets only the secrets its
        IAM role can read. A handler that needs a secret it wasn't given
        raises config.MissingSecret naming the field (never a value) before
        it reads the request; the C4 "missing secret fails" tests change to
        "missing secret is None and fails at use". Never logged: a secret
        value. For Vajra in infra/ (Slice 8b): every Lambda gets the
        SLACKKB_ settings; only the Lambdas above get the ARN env vars and
        secretsmanager:GetSecretValue on those ARNs alone.
- D-021 (2026-11-09) Citation format in answers (amends Slice 5/7's
        "Notes: <ids>" line). Vajra picked the brief and the time zone.
        After the answer, a "Notes:" line, then one line per cited note
        in the order the model cited them:
        "• <date and time>: <brief>". The date and time is Slack's date
        token <!date^EPOCH^{date_short_pretty} {time}|FALLBACK>, so each
        reader sees the note's created_at in their own Slack time zone;
        FALLBACK is "YYYY-MM-DD HH:MM UTC". The brief is the start of the
        note's own text: whitespace collapsed to single spaces, at most 80
        characters, cut at the last space before the limit with "…"
        appended when cut, then Slack-escaped like the answer (note text
        is data, D-016). No extra model call. A created_at that doesn't
        parse shows as its escaped raw string; a cited id with no
        retrieved note (qa already drops these) shows as the id. Note ids
        no longer appear in the reply; logs keep them (D-019).
        Amended 2026-11-09 (Vajra, after the first live answers): the
        brief repeated what the answer had just said, so it is dropped.
        Each line is now "• <date and time> in <#CHANNEL_ID>", the
        channel the note was saved in; Slack renders <#C…> as a channel
        link and it pings no one. The channel part is left out when
        channel_id isn't a plain Slack id (A–Z, 0–9). The date token and
        its fallbacks are unchanged; a created_at that raises ValueError or
        OverflowError when parsed shows as its escaped raw string.
        Severity (Vajra, same day): each line ends " · <SEVERITY>" (LOW,
        MEDIUM, HIGH, …, the value the modal set; LOW if never set), read
        from the notes table at answer time with store.get_note, since
        S3 holds content only and severity can change (D-009, D-014). The
        thread role gains dynamodb:GetItem on the notes table only. If the
        read fails or the note row is missing, the line has no severity
        part and a WARNING names the note_id; the answer is still posted.
        Amended 2026-11-10 (Vajra, after the live poison test, where an
        answer's prose named a raw note id): the qa system prompt tells the
        model never to write a note id in the answer text, only in
        cited_note_ids; and the reply replaces each occurrence of a given
        note's id in the answer text with "a saved note" before escaping,
        as a whole token only (not touching a letter, digit, "_" or "-" on
        either side), and logs one WARNING per replaced id naming the
        note_id (logs keep ids, D-019). The Notes: lines are unchanged,
        including the bare id shown for a cited id with no retrieved note.
- D-022 (2026-11-10) An answer that cites no notes says what was
        searched (Phase 5: every "found nothing" answer carries its query).
        Vajra OK'd Claude's draft. When retrieval returns notes but the
        answer cites none (cited_note_ids empty after qa drops unknown
        ids), the reply is the answer as now (ids replaced, escaped,
        D-021), then a blank line, then
        'Searched N notes for "<question>"; none cited.' N is the number
        of notes retrieved ("1 note" when N is 1), the question
        Slack-escaped like the answer. One INFO line is logged:
        "answer cited no notes, event_id=<id> notes=<N>". The empty-
        retrieval reply ('No notes match "<question>".') and replies that
        cite notes are unchanged. Fencing retrieved notes as data (the
        other Phase 5 item) already holds: D-016, D-021.
- D-023 (2026-11-12) An unexpected error in one SQS record fails only
        that record (C11 blind-review Minor, open since 10-23). In each
        queue handler (worker.handle, thread.handle, notify.handle), an
        Exception the record's processing doesn't already handle is
        caught for that record: one WARNING "record failed,
        <ExceptionClass>, message_id=<id>" is logged inside the record's
        trace, the record goes in batchItemFailures, and the rest of the
        batch is processed as usual. The exception's text is never
        logged (it can hold note text). Only Exception is caught; a
        record with no messageId still raises. Errors _process already
        handles keep their outcomes and log lines.
