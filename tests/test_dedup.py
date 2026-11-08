from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from slackkb.dedup import DedupError, claim, release

NOW = 1762600000


def _client_error():
    return ClientError({"Error": {"Code": "InternalServerError", "Message": "x"}}, "PutItem")


def test_claim_then_claim_again(events_table):
    assert claim(events_table, "Ev1", NOW) is True
    assert claim(events_table, "Ev1", NOW) is False
    assert claim(events_table, "Ev2", NOW) is True


def test_claim_sets_expires_at(events_table):
    claim(events_table, "Ev1", NOW)
    item = events_table.get_item(Key={"event_id": "Ev1"})["Item"]
    assert item == {"event_id": "Ev1", "expires_at": NOW + 3600}
    assert isinstance(item["expires_at"], Decimal)


def test_release_then_claim_again(events_table):
    assert claim(events_table, "Ev1", NOW)
    release(events_table, "Ev1")
    assert "Item" not in events_table.get_item(Key={"event_id": "Ev1"})
    assert claim(events_table, "Ev1", NOW) is True


def test_release_missing_is_ok(events_table):
    release(events_table, "never-claimed")


@pytest.mark.parametrize("exc", [_client_error(), BotoCoreError()])
def test_errors_wrap_as_dedup_error(exc):
    table = MagicMock()
    table.put_item.side_effect = exc
    table.delete_item.side_effect = exc
    with pytest.raises(DedupError) as info:
        claim(table, "Ev1", NOW)
    assert info.value.__cause__ is exc
    with pytest.raises(DedupError) as info:
        release(table, "Ev1")
    assert info.value.__cause__ is exc
