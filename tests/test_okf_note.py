import pytest
import yaml

from slackkb.models import Note, NoteStatus, Severity
from slackkb.okf_note import OkfNote, OkfNoteError, from_markdown, key_for, object_key, to_markdown

FIELDS = ("note_id", "team_id", "channel_id", "user_id", "created_at")


def _note(**over):
    base = {
        "note_id": "a" * 32,
        "team_id": "T000TEST",
        "channel_id": "C1",
        "user_id": "U1",
        "text": "db connection timeouts on /api/orders",
        "created_at": "2026-11-05T12:30:00.123456+00:00",
    }
    return Note(**{**base, **over})


def _assert_round_trip(note):
    parsed = from_markdown(to_markdown(note))
    assert isinstance(parsed, OkfNote)
    for field in FIELDS:
        assert getattr(parsed, field) == getattr(note, field)
    assert parsed.text == note.text


def test_note_round_trips_as_okf():
    note = _note(severity=Severity.HIGH, status=NoteStatus.ROUTED)
    md = to_markdown(note)
    frontmatter = {f: getattr(note, f) for f in FIELDS}
    assert md == "---\n" + yaml.safe_dump(frontmatter, sort_keys=True) + "---\n" + note.text
    _assert_round_trip(note)


def test_frontmatter_excludes_severity_status_and_text():
    note = _note(severity=Severity.CRITICAL, status=NoteStatus.ROUTED, text="unique-body-text")
    md = to_markdown(note)
    head = md.split("---\n")[1]
    assert set(yaml.safe_load(head)) == set(FIELDS)
    for absent in ("severity", "status", "CRITICAL", "ROUTED", "unique-body-text"):
        assert absent not in head
    assert md.endswith("---\nunique-body-text")


@pytest.mark.parametrize(
    "text",
    [
        "line\n---\nmore",
        "---\n---\n",
        "---\nnote_id: evil\n---\nx",
        "key: value\nlist:\n  - a\n  - b\n",
        "# heading\n\n- bullet: yes\n",
    ],
)
def test_body_with_delimiter_and_yaml_round_trips(text):
    _assert_round_trip(_note(text=text))


@pytest.mark.parametrize(
    "over",
    [
        {"note_id": "1e10"},
        {"note_id": "0123"},
        {"note_id": "123456"},
        {"note_id": "true"},
        {"note_id": "null"},
        {"team_id": "0x1F"},
        {"channel_id": "1_000"},
        {"user_id": "yes"},
        {"created_at": "2026-11-05"},
        {"created_at": "2026-11-05T12:30:00+00:00"},
        {"text": ""},
        {"text": "trailing newline\n"},
        {"text": "unicode: héllo — 日本語 🚀"},
        {"user_id": "ünï: \"quoted\" #x"},
    ],
)
def test_yaml_lookalike_values_stay_strings(over):
    note = _note(**over)
    _assert_round_trip(note)
    parsed = from_markdown(to_markdown(note))
    for field in FIELDS:
        assert isinstance(getattr(parsed, field), str)


VALID_HEAD = (
    "note_id: abc\nteam_id: T1\nchannel_id: C1\nuser_id: U1\n"
    "created_at: '2026-11-05T00:00:00+00:00'\n"
)


@pytest.mark.parametrize(
    ("md", "reason"),
    [
        ("note_id: abc\n", "missing opening delimiter"),
        ("", "missing opening delimiter"),
        ("--- \n" + VALID_HEAD + "---\nbody", "missing opening delimiter"),  # not an exact line
        ("---\n" + VALID_HEAD + "body", "missing closing delimiter"),
        ("---\n" + VALID_HEAD + "---", "missing closing delimiter"),  # no newline, no real line
        ("---\n", "missing closing delimiter"),
        ("---\n- a\n- b\n---\nbody", "not a mapping"),  # sequence frontmatter
        ("---\njust a string\n---\nbody", "not a mapping"),  # scalar frontmatter
        ("---\n---\nbody", "not a mapping"),  # empty frontmatter
        ("---\n: : [\n---\nbody", "not valid YAML"),
        ("---\n" + VALID_HEAD.replace("team_id: T1\n", "") + "---\nbody", "invalid frontmatter"),
        ("---\n" + VALID_HEAD + "severity: HIGH\n---\nbody", "invalid frontmatter"),  # unknown key
        (
            "---\n" + VALID_HEAD.replace("note_id: abc", "note_id: 123") + "---\nbody",
            "invalid frontmatter",  # not a string
        ),
    ],
)
def test_malformed_markdown_raises(md, reason):
    with pytest.raises(OkfNoteError, match=reason):
        from_markdown(md)


@pytest.mark.parametrize(
    "line",
    ["created_at: 2026-13-45", "note_id: 0x_"],
)
def test_yaml_value_errors_become_okf_note_error(line):
    key = line.split(":")[0]
    head = "".join(
        (line if row.startswith(key + ":") else row) + "\n" for row in VALID_HEAD.splitlines()
    )
    with pytest.raises(OkfNoteError):
        from_markdown("---\n" + head + "---\nbody")


@pytest.mark.parametrize(
    "line",
    [
        'note_id: !!int ""',
        "note_id: !!bool foo",
        "created_at: !!timestamp foo",
        'note_id: !!binary "@@"',
        "note_id: !!binary aGVsbG8=",
        "note_id: 123",
        "note_id:",
        "created_at: 2026-01-02",
    ],
)
def test_bad_frontmatter_values_become_okf_note_error(line):
    key = line.split(":")[0]
    head = "".join(
        (line if row.startswith(key + ":") else row) + "\n" for row in VALID_HEAD.splitlines()
    )
    with pytest.raises(OkfNoteError):
        from_markdown("---\n" + head + "---\nbody")


def test_any_safe_load_exception_becomes_okf_note_error(monkeypatch):
    def boom(_):
        raise TypeError("boom")

    monkeypatch.setattr(yaml, "safe_load", boom)
    with pytest.raises(OkfNoteError) as info:
        from_markdown("---\n" + VALID_HEAD + "---\nbody")
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_key_for_matches_object_key():
    n = _note()
    assert key_for(n.team_id, n.note_id) == object_key(n)
    assert key_for("T9", "x") == "notes/T9/x.md"


def test_okf_note_error_is_value_error():
    assert issubclass(OkfNoteError, ValueError)


def test_object_key():
    assert object_key(_note()) == f"notes/T000TEST/{'a' * 32}.md"
