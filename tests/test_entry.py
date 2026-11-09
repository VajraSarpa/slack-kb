import importlib
import inspect
import logging

import pytest

from slackkb import config, entry

SIGNING_ARN = "arn:aws:secretsmanager:us-east-1:1:secret:signing"
TOKEN_ARN = "arn:aws:secretsmanager:us-east-1:1:secret:token"
SIGNING_VALUE = "fetched-signing-value"
TOKEN_VALUE = "xoxb-fetched-token-value"
NOW = 1_700_000_000


class Fake:
    def __init__(self, kind, name=None):
        self.kind = kind
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Fake) and (self.kind, self.name) == (other.kind, other.name)

    def __hash__(self):
        return hash((self.kind, self.name))


class SecretsFake:
    def __init__(self, values, fail_first=False):
        self.values = values
        self.calls = []
        self.fail_first = fail_first

    def get_secret_value(self, SecretId):
        self.calls.append(SecretId)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("boom")
        return {"SecretString": self.values[SecretId]}


class FakeSession:
    def __init__(self, secrets):
        self.secrets = secrets
        self.clients = {}

    def client(self, service):
        if service == "secretsmanager":
            return self.secrets
        return self.clients.setdefault(service, Fake("client", service))

    def resource(self, service):
        class Res:
            def Table(self, name):
                return Fake("table", name)

            def Bucket(self, name):
                return Fake("bucket", name)

        assert service in ("dynamodb", "s3")
        return Res()


@pytest.fixture
def env(monkeypatch):
    entry.reset()
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SLACKKB_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.example/capture")
    monkeypatch.setenv("SIGNING_SECRET_ARN", SIGNING_ARN)
    monkeypatch.setenv("SLACK_BOT_TOKEN_ARN", TOKEN_ARN)
    monkeypatch.setattr(entry.time, "time", lambda: NOW + 0.7)
    secrets = SecretsFake({SIGNING_ARN: SIGNING_VALUE, TOKEN_ARN: TOKEN_VALUE})
    session = FakeSession(secrets)
    calls = []

    def make_session():
        calls.append(1)
        return session

    monkeypatch.setattr(entry, "_session", make_session)
    configure = []
    monkeypatch.setattr(entry.obs, "configure", lambda *a, **k: configure.append(1))
    yield session, secrets, calls, configure
    entry.reset()


def record(monkeypatch, module, ret="ret"):
    seen = []
    signature = inspect.signature(module.handle)

    def handle(event, **kwargs):
        signature.bind(event, **kwargs)  # every keyword the real handle() takes
        seen.append((event, kwargs))
        return ret

    monkeypatch.setattr(module, "handle", handle)
    return seen


def test_import_makes_no_aws_call(monkeypatch):
    import boto3

    def boom(*a, **k):
        raise AssertionError("no session at import")

    monkeypatch.setattr(boto3.session, "Session", boom)
    importlib.reload(entry)
    entry.reset()


def test_capture_handler_loads_only_its_secret(env, monkeypatch):
    session, secrets, _, _ = env
    seen = record(monkeypatch, entry.capture)
    assert entry.capture_handler({"e": 1}, None) == "ret"
    assert secrets.calls == [SIGNING_ARN]
    _, kw = seen[0]
    assert kw["table"] == Fake("table", "slackkb-notes-test")
    assert kw["sqs"] is session.clients["sqs"]
    assert kw["settings"].signing_secret.get_secret_value() == SIGNING_VALUE
    assert kw["settings"].slack_bot_token is None
    assert kw["now"] == NOW


@pytest.mark.parametrize(
    ("name", "module", "expected"),
    [
        ("events_handler", "events", [SIGNING_ARN]),
        ("modal_handler", "modal", [SIGNING_ARN, TOKEN_ARN]),
        ("thread_handler", "thread", [TOKEN_ARN]),
        ("worker_handler", "worker", []),
        ("notify_handler", "notify", []),
    ],
)
def test_each_handler_fetches_only_its_secrets(env, monkeypatch, name, module, expected):
    _, secrets, _, _ = env
    record(monkeypatch, getattr(entry, module))
    getattr(entry, name)({}, None)
    assert secrets.calls == expected


@pytest.mark.parametrize(
    "name",
    [
        "capture_handler",
        "modal_handler",
        "events_handler",
        "worker_handler",
        "notify_handler",
        "thread_handler",
    ],
)
def test_handler_returns_what_handle_returns(env, monkeypatch, name):
    module = getattr(entry, name.removesuffix("_handler"))
    seen = record(monkeypatch, module, ret={"sentinel": name})
    event = {"x": name}
    assert getattr(entry, name)(event, object()) == {"sentinel": name}
    assert seen[0][0] is event


def test_cold_start_runs_once(env, monkeypatch):
    _, secrets, session_calls, configure = env
    record(monkeypatch, entry.capture)
    built = []
    real = entry.Settings

    def counting(**kw):
        built.append(1)
        return real(**kw)

    monkeypatch.setattr(entry, "Settings", counting)
    entry.capture_handler({}, None)
    entry.capture_handler({}, None)
    assert len(secrets.calls) == 1
    assert len(built) == 1
    assert len(session_calls) == 1
    assert len(configure) == 1


def test_failed_secret_fetch_raises_and_caches_nothing(env, monkeypatch):
    session, _, _, _ = env
    secrets = SecretsFake({SIGNING_ARN: SIGNING_VALUE}, fail_first=True)
    session.secrets = secrets
    seen = record(monkeypatch, entry.capture)
    with pytest.raises(RuntimeError):
        entry.capture_handler({}, None)
    assert not seen
    assert entry.capture_handler({}, None) == "ret"
    assert secrets.calls == [SIGNING_ARN, SIGNING_ARN]


def test_missing_arn_env_fails_at_use(env, monkeypatch):
    _, secrets, _, _ = env
    monkeypatch.delenv("SIGNING_SECRET_ARN")
    with pytest.raises(config.MissingSecret):
        entry.capture_handler({}, None)
    assert secrets.calls == []


def test_worker_and_notify_bindings(env, monkeypatch):
    session, _, _, _ = env
    worker_seen = record(monkeypatch, entry.worker)
    notify_seen = record(monkeypatch, entry.notify)
    embeds = []
    monkeypatch.setattr(
        entry,
        "embed_text",
        lambda client, *, model_id, text: embeds.append((client, model_id, text)) or [0.5],
    )
    transports = []

    def make_transport(timeout):
        transports.append(timeout)
        return ("transport", timeout)

    posts = []
    monkeypatch.setattr(entry, "make_response_url_transport", make_transport)
    monkeypatch.setattr(entry, "post_response_url", lambda *a: posts.append(a))

    entry.worker_handler({}, None)
    kw = worker_seen[0][1]
    assert kw["embed"]("hello") == [0.5]
    settings = config.Settings()
    assert embeds == [(session.clients["bedrock-runtime"], settings.embed_model_id, "hello")]
    assert kw["vectors_table"] == Fake("table", settings.vectors_table)

    assert kw["table"] == Fake("table", settings.notes_table)
    assert kw["bucket"] == Fake("bucket", settings.notes_bucket)

    entry.notify_handler({}, None)
    nkw = notify_seen[0][1]
    assert nkw["table"] == Fake("table", settings.notes_table)
    assert nkw["bucket"] == Fake("bucket", settings.notes_bucket)
    assert nkw["vectors_table"] == Fake("table", settings.vectors_table)
    nkw["post"]("https://x", "hi")
    assert transports == [10.0]
    assert posts == [("https://x", "hi", ("transport", 10.0))]


def test_thread_and_modal_bindings(env, monkeypatch):
    session, _, _, _ = env
    thread_seen = record(monkeypatch, entry.thread)
    modal_seen = record(monkeypatch, entry.modal)
    bound = []

    def bind(settings, *, bedrock, vectors_table, bucket):
        bound.append((settings, bedrock, vectors_table, bucket))
        return "retrieve", "answer"

    monkeypatch.setattr(entry.thread, "bind", bind)
    monkeypatch.setattr(entry.thread, "slack_client", lambda s: ("slack", s))

    entry.thread_handler({}, None)
    settings, bedrock, vectors, bucket = bound[0]
    assert bedrock is session.clients["bedrock-runtime"]
    assert vectors == Fake("table", settings.vectors_table)
    assert bucket == Fake("bucket", settings.notes_bucket)
    kw = thread_seen[0][1]
    assert (kw["retrieve"], kw["answer"]) == ("retrieve", "answer")
    assert kw["slack"] == ("slack", settings)

    entry.modal_handler({}, None)
    slack = modal_seen[0][1]["slack"]
    assert isinstance(slack, entry.SlackClient)
    assert slack._token.get_secret_value() == TOKEN_VALUE
    mkw = modal_seen[0][1]
    assert mkw["table"] == Fake("table", settings.notes_table)
    assert mkw["now"] == NOW


def test_events_bindings(env, monkeypatch):
    session, _, _, _ = env
    seen = record(monkeypatch, entry.events)
    entry.events_handler({}, None)
    kw = seen[0][1]
    assert kw["events_table"] == Fake("table", kw["settings"].events_table)
    assert kw["sqs"] is session.clients["sqs"]
    assert kw["settings"].signing_secret.get_secret_value() == SIGNING_VALUE
    assert kw["now"] == NOW


def test_no_secret_in_logs(env, monkeypatch, caplog):
    record(monkeypatch, entry.modal)
    with caplog.at_level(logging.DEBUG):
        entry.modal_handler({}, None)
    text = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert SIGNING_VALUE not in text
    assert TOKEN_VALUE not in text
