"""Slice 8c: pin what the decisions require of infra/template.yaml (D-004, D-014,
D-017, D-018, D-020). Each check is a plain function over the loaded template;
the mutant test proves every check fails on a broken in-memory copy."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from slackkb.config import Settings

TEMPLATE = Path(__file__).resolve().parent.parent / "infra" / "template.yaml"
NAMES = ["Capture", "Modal", "Events", "Worker", "Notify", "Thread"]
SECRET_FIELDS = {"signing_secret", "slack_bot_token"}


class _CfnLoader(yaml.SafeLoader):
    pass


def _short_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {("Ref" if suffix == "Ref" else f"Fn::{suffix}"): value}


_CfnLoader.add_multi_constructor("!", _short_tag)


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(), Loader=_CfnLoader)  # noqa: S506


# ---------- helpers ----------


def _list(value):
    return value if isinstance(value, list) else [value]


def _resources(tpl, rtype):
    return {k: v for k, v in tpl["Resources"].items() if v["Type"] == rtype}


def _function(tpl, name):
    return tpl["Resources"][f"{name}Function"]["Properties"]


def _fn_env(tpl, name):
    return _function(tpl, name).get("Environment", {}).get("Variables", {})


def _effective_env(tpl, name):
    """What the Lambda actually gets: Globals variables overlaid by its own."""
    glob = tpl.get("Globals", {}).get("Function", {})
    return {**glob.get("Environment", {}).get("Variables", {}), **_fn_env(tpl, name)}


def _role_statements(tpl, name):
    role = tpl["Resources"][f"{name}Role"]["Properties"]
    return [
        s
        for p in role.get("Policies", [])
        for s in _list(p["PolicyDocument"]["Statement"])
    ]


def _ref(value):
    return value["Ref"] if isinstance(value, dict) and "Ref" in value else json.dumps(value)


def _secret_resources(tpl, name):
    """Resources of Allow GetSecretValue statements, as Ref names."""
    out = []
    for s in _role_statements(tpl, name):
        if s["Effect"] == "Allow" and "secretsmanager:getsecretvalue" in [
            a.lower() for a in _list(s["Action"])
        ]:
            out += [_ref(r) for r in _list(s["Resource"])]
    return sorted(out)


def _getatt(value):
    return value["Fn::GetAtt"].split(".")[0]


def _timeout(tpl, name):
    return _function(tpl, name)["Timeout"]


def _queue_props(tpl, name):
    return tpl["Resources"][name]["Properties"]


def _sqs_event(tpl, fn):
    events = [
        e["Properties"]
        for e in _function(tpl, fn)["Events"].values()
        if e["Type"] == "SQS"
    ]
    assert len(events) == 1, f"{fn} needs exactly one SQS event"
    return events[0]


# ---------- checks ----------


def check_no_wildcard_iam(tpl):
    roles = _resources(tpl, "AWS::IAM::Role")
    assert roles
    for rid, role in roles.items():
        props = role["Properties"]
        assert "ManagedPolicyArns" not in props, rid
        for policy in props.get("Policies", []):
            for s in _list(policy["PolicyDocument"]["Statement"]):
                if s["Effect"] != "Allow":
                    continue
                for a in _list(s["Action"]):
                    assert "*" not in a, f"{rid}: wildcard action {a}"
                for r in _list(s["Resource"]):
                    assert r != "*", f"{rid}: Resource *"
    for name in NAMES:
        assert "Policies" not in _function(tpl, name), name


def check_handler_and_role(tpl):
    roles = []
    for name in NAMES:
        props = _function(tpl, name)
        assert props["Handler"] == f"slackkb.entry.{name.lower()}_handler"
        assert props["Role"] == {"Fn::GetAtt": f"{name}Role.Arn"}, name
        roles.append(json.dumps(props["Role"]))
    assert len(set(roles)) == 6


def check_secret_arn_env(tpl):
    expected = {
        "SIGNING_SECRET_ARN": ("SigningSecretArn", {"Capture", "Modal", "Events"}),
        "SLACK_BOT_TOKEN_ARN": ("SlackBotTokenArn", {"Modal", "Thread"}),
    }
    for var, (param, owners) in expected.items():
        for name in NAMES:
            env = _effective_env(tpl, name)
            if name in owners:
                assert env.get(var) == {"Ref": param}, f"{name} {var}"
            else:
                assert var not in env, f"{name} must not have {var}"
    assert not _resources(tpl, "AWS::SecretsManager::Secret")


def check_secret_reads(tpl):
    signing, token = "SigningSecretArn", "SlackBotTokenArn"
    expected = {
        "Capture": [signing],
        "Events": [signing],
        "Modal": sorted([signing, token]),
        "Thread": [token],
        "Worker": [],
        "Notify": [],
    }
    for name, want in expected.items():
        assert _secret_resources(tpl, name) == want, name
    for name in NAMES:
        for s in _role_statements(tpl, name):
            if s["Effect"] != "Allow":
                continue
            for a in _list(s["Action"]):
                if a.lower().startswith("secretsmanager:"):
                    assert a.lower() == "secretsmanager:getsecretvalue", f"{name}: {a}"


def check_settings_env(tpl):
    fields = [f for f in Settings.model_fields if f not in SECRET_FIELDS]
    assert fields
    glob = tpl["Globals"]["Function"]["Environment"]["Variables"]
    for f in fields:
        assert f"SLACKKB_{f.upper()}" in glob, f
    text = json.dumps(tpl)
    assert "SLACKKB_SIGNING_SECRET" not in text
    assert "SLACKKB_SLACK_BOT_TOKEN" not in text


def check_dlq_window(tpl):
    cq = _queue_props(tpl, "CaptureQueue")
    redrive = cq["RedrivePolicy"]
    assert _getatt(redrive["deadLetterTargetArn"]) == "CaptureDlq"
    assert redrive["maxReceiveCount"] * cq["VisibilityTimeout"] < 1800
    qq = _queue_props(tpl, "QuestionQueue")
    assert _getatt(qq["RedrivePolicy"]["deadLetterTargetArn"]) == "QuestionDlq"


def check_visibility(tpl):
    for queue, fn in [("CaptureQueue", "Worker"), ("QuestionQueue", "Thread")]:
        vis = _queue_props(tpl, queue)["VisibilityTimeout"]
        assert vis >= 6 * _timeout(tpl, fn), queue


def check_consumers(tpl):
    for fn, queue in [
        ("Worker", "CaptureQueue"),
        ("Notify", "CaptureDlq"),
        ("Thread", "QuestionQueue"),
    ]:
        ev = _sqs_event(tpl, fn)
        assert _getatt(ev["Queue"]) == queue, fn
        assert "ReportBatchItemFailures" in ev["FunctionResponseTypes"], fn


def check_bucket(tpl):
    props = tpl["Resources"]["NotesBucket"]["Properties"]
    assert "VersioningConfiguration" not in props
    pab = props["PublicAccessBlockConfiguration"]
    for flag in (
        "BlockPublicAcls",
        "BlockPublicPolicy",
        "IgnorePublicAcls",
        "RestrictPublicBuckets",
    ):
        assert pab.get(flag) is True, flag
    policy = tpl["Resources"]["NotesBucketPolicy"]["Properties"]
    assert policy["Bucket"] == {"Ref": "NotesBucket"}
    stmts = _list(policy["PolicyDocument"]["Statement"])
    assert any(
        s["Effect"] == "Deny"
        and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
        for s in stmts
    )


# ---------- tests ----------


def test_no_wildcard_iam(template):
    check_no_wildcard_iam(template)


def test_each_function_has_its_handler_and_role(template):
    check_handler_and_role(template)


def test_secret_arn_env_per_function(template):
    check_secret_arn_env(template)


def test_each_role_reads_only_its_secrets(template):
    check_secret_reads(template)


def test_every_function_gets_the_settings(template):
    check_settings_env(template)


def test_capture_dlq_inside_response_url_window(template):
    check_dlq_window(template)


def test_queue_visibility_covers_the_consumer_timeout(template):
    check_visibility(template)


def test_queue_consumers(template):
    check_consumers(template)


def test_bucket_is_locked_down(template):
    check_bucket(template)


# ---------- mutants: each edit must make its check fail ----------


def _m_allow_star(t):
    t["Resources"]["CaptureRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {"Effect": "Allow", "Action": "sqs:SendMessage", "Resource": "*"}
    )


def _m_action_star(t):
    t["Resources"]["WorkerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {"Effect": "Allow", "Action": "s3:*", "Resource": {"Ref": "NotesBucket"}}
    )


def _m_managed(t):
    admin = "arn:aws:iam::aws:policy/AdministratorAccess"
    t["Resources"]["ModalRole"]["Properties"]["ManagedPolicyArns"] = [admin]


def _m_sam_policies(t):
    _function(t, "Notify")["Policies"] = ["AWSLambdaBasicExecutionRole"]


def _m_shared_role(t):
    _function(t, "Notify")["Role"] = {"Fn::GetAtt": "WorkerRole.Arn"}


def _m_bad_handler(t):
    _function(t, "Thread")["Handler"] = "slackkb.entry.worker_handler"


def _m_token_on_capture(t):
    _fn_env(t, "Capture")["SLACK_BOT_TOKEN_ARN"] = {"Ref": "SlackBotTokenArn"}


def _m_signing_in_globals(t):
    glob = t["Globals"]["Function"]["Environment"]["Variables"]
    glob["SIGNING_SECRET_ARN"] = {"Ref": "SigningSecretArn"}


def _m_secret_resource(t):
    t["Resources"]["Sneaky"] = {"Type": "AWS::SecretsManager::Secret", "Properties": {}}


def _m_worker_reads_secret(t):
    t["Resources"]["WorkerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": {"Ref": "SlackBotTokenArn"},
        }
    )


def _m_other_secret_action(t):
    t["Resources"]["ThreadRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "secretsmanager:DescribeSecret",
            "Resource": {"Ref": "SlackBotTokenArn"},
        }
    )


def _m_worker_reads_secret_mixed_case(t):
    t["Resources"]["WorkerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "SecretsManager:GetSecretValue",
            "Resource": {"Ref": "SigningSecretArn"},
        }
    )


def _m_other_secret_action_mixed_case(t):
    t["Resources"]["ThreadRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "SecretsManager:DescribeSecret",
            "Resource": {"Ref": "SlackBotTokenArn"},
        }
    )


def _m_policy_on_other_bucket(t):
    t["Resources"]["NotesBucketPolicy"]["Properties"]["Bucket"] = {"Ref": "OtherBucket"}


def _m_drop_setting(t):
    del t["Globals"]["Function"]["Environment"]["Variables"]["SLACKKB_EVENTS_TABLE"]


def _m_secret_in_env(t):
    t["Globals"]["Function"]["Environment"]["Variables"]["SLACKKB_SIGNING_SECRET"] = "x"


def _m_max_receive(t):
    _queue_props(t, "CaptureQueue")["RedrivePolicy"]["maxReceiveCount"] = 20


def _m_wrong_dlq(t):
    redrive = _queue_props(t, "QuestionQueue")["RedrivePolicy"]
    redrive["deadLetterTargetArn"] = {"Fn::GetAtt": "CaptureDlq.Arn"}


def _m_short_visibility(t):
    _queue_props(t, "QuestionQueue")["VisibilityTimeout"] = 60


def _m_slow_worker(t):
    _function(t, "Worker")["Timeout"] = 120


def _m_wrong_queue(t):
    _sqs_event(t, "Notify")["Queue"] = {"Fn::GetAtt": "CaptureQueue.Arn"}


def _m_no_partial(t):
    _sqs_event(t, "Worker")["FunctionResponseTypes"] = []


def _m_pab_off(t):
    pab = t["Resources"]["NotesBucket"]["Properties"]["PublicAccessBlockConfiguration"]
    pab["RestrictPublicBuckets"] = False


def _m_versioning(t):
    t["Resources"]["NotesBucket"]["Properties"]["VersioningConfiguration"] = {"Status": "Enabled"}


def _m_no_deny(t):
    t["Resources"]["NotesBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"] = []


MUTANTS = [
    (check_no_wildcard_iam, _m_allow_star),
    (check_no_wildcard_iam, _m_action_star),
    (check_no_wildcard_iam, _m_managed),
    (check_no_wildcard_iam, _m_sam_policies),
    (check_handler_and_role, _m_shared_role),
    (check_handler_and_role, _m_bad_handler),
    (check_secret_arn_env, _m_token_on_capture),
    (check_secret_arn_env, _m_signing_in_globals),
    (check_secret_arn_env, _m_secret_resource),
    (check_secret_reads, _m_worker_reads_secret),
    (check_secret_reads, _m_other_secret_action),
    (check_secret_reads, _m_worker_reads_secret_mixed_case),
    (check_secret_reads, _m_other_secret_action_mixed_case),
    (check_settings_env, _m_drop_setting),
    (check_settings_env, _m_secret_in_env),
    (check_dlq_window, _m_max_receive),
    (check_dlq_window, _m_wrong_dlq),
    (check_visibility, _m_short_visibility),
    (check_visibility, _m_slow_worker),
    (check_consumers, _m_wrong_queue),
    (check_consumers, _m_no_partial),
    (check_bucket, _m_pab_off),
    (check_bucket, _m_versioning),
    (check_bucket, _m_no_deny),
    (check_bucket, _m_policy_on_other_bucket),
]


@pytest.mark.parametrize(
    ("check", "mutate"), MUTANTS, ids=[f"{c.__name__}-{m.__name__}" for c, m in MUTANTS]
)
def test_check_fails_on_mutant(template, check, mutate):
    check(template)
    broken = copy.deepcopy(template)
    mutate(broken)
    with pytest.raises(AssertionError):
        check(broken)


def test_secret_reads_ignore_action_case(template):
    tpl = copy.deepcopy(template)
    rewritten = 0
    for s in _role_statements(tpl, "Modal"):
        actions = _list(s["Action"])
        new = [
            "SECRETSMANAGER:GETSECRETVALUE"
            if a.lower() == "secretsmanager:getsecretvalue"
            else a
            for a in actions
        ]
        rewritten += sum(a != b for a, b in zip(actions, new, strict=True))
        s["Action"] = new if isinstance(s["Action"], list) else new[0]
    assert rewritten
    check_secret_reads(tpl)
