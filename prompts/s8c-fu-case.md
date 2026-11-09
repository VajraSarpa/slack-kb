GOAL
Slice 8c follow-up: close two gaps the reviews found in tests/test_infra.py
(personal_1712bfec). IAM action names are case-insensitive, but the
secretsmanager checks compare them exactly; and the bucket check never
looks at which bucket the TLS-deny policy is attached to.

SCOPE (only these paths may change)
- tests/test_infra.py

CONTEXT
- 513 tests pass on main; infra/template.yaml and every src file stay as
  they are. No other test file changes.
- The checks are plain functions (check_secret_reads, check_bucket, ...),
  helpers like _secret_resources, and a MUTANTS table of
  (check, mutate) pairs; test_check_fails_on_mutant applies each mutate to
  a deep copy of the loaded template and asserts the check fails.
- Operator mutants on the template file that survive today: an Allow on
  WorkerRole with Action "SecretsManager:GetSecretValue" and Resource
  !Ref SigningSecretArn; NotesBucketPolicy's Bucket changed to another Ref.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Every action-name comparison in the secretsmanager checks
   (_secret_resources and check_secret_reads) is case-insensitive: an
   action is matched after lower-casing both sides. So
   "SecretsManager:GetSecretValue" on WorkerRole fails check_secret_reads
   (worker reads no secret), and "secretsmanager:describesecret" or
   "SecretsManager:DescribeSecret" on any role fails it (no other
   secretsmanager action).
2. check_bucket also asserts NotesBucketPolicy's Properties.Bucket is
   {"Ref": "NotesBucket"}.
3. Nothing else in the checks changes meaning; every existing MUTANTS
   entry still fails its check and the real template still passes.

TESTS (red first)
Add these MUTANTS entries and their _m_ functions first, run
`python -m pytest tests/test_infra.py -q`, and see the new
test_check_fails_on_mutant cases fail (the current checks pass on them);
then change the checks:
- (check_secret_reads, _m_worker_reads_secret_mixed_case): Allow
  "SecretsManager:GetSecretValue" on WorkerRole, Resource Ref
  SigningSecretArn. (req 1)
- (check_secret_reads, _m_other_secret_action_mixed_case): Allow
  "SecretsManager:DescribeSecret" on ThreadRole, Resource Ref
  SlackBotTokenArn. (req 1)
- (check_bucket, _m_policy_on_other_bucket): NotesBucketPolicy Bucket
  {"Ref": "OtherBucket"}. (req 2)
And one plain test, not a mutant:
- test_secret_reads_ignore_action_case: on a deep copy where ModalRole's
  GetSecretValue action is rewritten "SECRETSMANAGER:GETSECRETVALUE" (same
  grant, same resources), check_secret_reads passes. (req 1: the same
  grant in another case is still counted as modal's two reads)
Say in your summary which of these failed before the check change (all
four should).

NON-GOALS
- infra/, src, other tests; new requirements beyond these two gaps.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` and
  `cfn-lint infra/template.yaml` pass.
- The diff touches only tests/test_infra.py.
