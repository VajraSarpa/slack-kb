GOAL
Slice 8c (D-005): tests/test_infra.py, tests that read infra/template.yaml
and pin what the decisions require of it: least-privilege IAM with no
wildcard grant, each Lambda reading only its own secrets, the capture DLQ
inside response_url's window, and the bucket locked down. infra/ itself is
human-authored and does not change.

SCOPE (only these paths may change)
- tests/test_infra.py          new tests

CONTEXT
- Slices 1-9b and 8a are merged; all 482 existing tests must stay green and
  no existing test line, src file or infra/ file changes.
- infra/template.yaml (Slice 8b) is the subject. It is a SAM template with
  CloudFormation short tags (!Ref, !Sub, !GetAtt). yaml.safe_load rejects
  those tags: load it with a yaml.SafeLoader subclass that adds a
  multi-constructor for "!", turning `!Ref X` into {"Ref": "X"},
  `!GetAtt A.B` into {"Fn::GetAtt": "A.B"}, and `!Sub s` into {"Fn::Sub": s}
  (a scalar, sequence or mapping node each keeps its value). pyyaml is
  already a dependency. Load the template once per module (a fixture).
- docs/DECISIONS.md D-004, D-017, D-018, D-020 apply. The template's
  logical ids: functions CaptureFunction, ModalFunction, EventsFunction,
  WorkerFunction, NotifyFunction, ThreadFunction; roles CaptureRole ...
  ThreadRole (one per function, inline Policies); queues CaptureQueue,
  CaptureDlq, QuestionQueue, QuestionDlq; bucket NotesBucket with
  NotesBucketPolicy; parameters SigningSecretArn, SlackBotTokenArn.
- The `*`s the template has on purpose, none of them a wildcard grant:
  the log-group ARN's `:*` stream suffix (from !GetAtt <X>Logs.Arn),
  `${NotesBucket.Arn}/notes/*` object resources, the region `*` in D-012's
  `arn:aws:bedrock:*::foundation-model/...`, and the bucket policy's
  DenyInsecureTransport (Effect Deny, Principal "*", Action s3:*). A Deny
  grants nothing, so the wildcard rule covers Allow statements only.
- Tests run with --disable-socket; no test calls AWS or runs cfn-lint.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS (each one a test below)
1. No IAM role grants a wildcard: in every AWS::IAM::Role's inline policy
   statements with Effect Allow, no action is "*" or ends with ":*" or
   contains "*", and no resource is the literal string "*". No role has
   ManagedPolicyArns, and no function has SAM `Policies` (only `Role`).
2. Six functions, each with its handler slackkb.entry.<name>_handler and
   its own role (six distinct Role references, each to <Name>Role).
3. Secret ARN env vars (D-020): SIGNING_SECRET_ARN is set on capture,
   modal and events only; SLACK_BOT_TOKEN_ARN on modal and thread only;
   each is a Ref to its parameter. No AWS::SecretsManager::Secret resource.
4. secretsmanager:GetSecretValue: capture and events roles allow it on
   SigningSecretArn only, modal on both, thread on SlackBotTokenArn only,
   worker and notify not at all; no role allows any other secretsmanager
   action.
5. Every Function gets every non-secret Settings field as an SLACKKB_ env
   var through Globals (the field names from slackkb.config.Settings
   minus signing_secret and slack_bot_token, upper-cased with the prefix),
   and no SLACKKB_SIGNING_SECRET / SLACKKB_SLACK_BOT_TOKEN appears anywhere
   in the template.
6. Queues (D-004, D-017, D-018): CaptureQueue redrives to CaptureDlq and
   QuestionQueue to QuestionDlq; for CaptureQueue, maxReceiveCount x
   VisibilityTimeout is under 1800 s (response_url's 30 min); each queue's
   VisibilityTimeout is at least 6 x the Timeout of the function that
   consumes it (worker for CaptureQueue, thread for QuestionQueue).
7. Event sources: worker consumes CaptureQueue, notify consumes CaptureDlq,
   thread consumes QuestionQueue, each with ReportBatchItemFailures.
8. Bucket (D-014): all four PublicAccessBlockConfiguration flags true, no
   VersioningConfiguration, and NotesBucketPolicy has a Deny on
   aws:SecureTransport "false".

TESTS (write first; run them and see each fail on a broken copy, see below)
All in tests/test_infra.py:
- test_no_wildcard_iam (req 1)
- test_each_function_has_its_handler_and_role (req 2)
- test_secret_arn_env_per_function (req 3)
- test_each_role_reads_only_its_secrets (req 4)
- test_every_function_gets_the_settings (req 5)
- test_capture_dlq_inside_response_url_window (req 6)
- test_queue_visibility_covers_the_consumer_timeout (req 6)
- test_queue_consumers (req 7)
- test_bucket_is_locked_down (req 8)
The tests pass on the current template, so red evidence comes from
mutants: for each test, show in your summary one edit to an in-memory copy
of the loaded template (not the file) that makes it fail, e.g. an Allow
statement with Resource "*", SLACK_BOT_TOKEN_ARN added to capture,
maxReceiveCount 20. A parametrized helper test that applies such edits to
a deep copy and asserts the check function fails is welcome; keep each
check as a plain function the tests call.

NON-GOALS
- Changing infra/template.yaml, any src file or any existing test.
- Running cfn-lint or sam from the tests; deploying (8d).

DONE WHEN
- `cfn-lint infra/template.yaml` and `python -m pytest` and
  `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
