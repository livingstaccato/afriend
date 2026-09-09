"""Deriving critique quorum from the friend audit rows.

`successful_friend_ids_from_audit` is what a saved `successful_friend_ids`
is checked against, so what it counts as a success -- and what it refuses to
guess at -- decides whether an edited run.json can buy a participation floor
it never met. These are its rules on their own, without a run directory.
"""

import pytest

from afriend.commands.checkpoint import successful_friend_ids_from_audit
from afriend.errors import UsageError


def _friend_row(name: str, round_no: int, status: str) -> dict[str, object]:
    return {
        "name": name,
        "model": None,
        "effort": None,
        "round": round_no,
        "status": status,
    }


@pytest.mark.parametrize(
    ("first_status", "second_status"),
    [
        ("ok", "ok [orphans suspected]"),
        ("failed: exit 1", "failed: timeout"),
        ("ok", "OK"),
        ("ok", " ok"),
        ("failed: exit 1", "FAILED: exit 1"),
        ("failed: exit 1", "failed: exit 1 "),
    ],
)
def test_derivation_rejects_nonidentical_duplicate_statuses(first_status, second_status):
    """Two rows for one friend that disagree leave no answer to derive. The
    near-miss pairs are here because a case-fold or a stray space would make
    conflicting rows read as one."""
    rows = [
        _friend_row("fake-good-0", 1, first_status),
        _friend_row("fake-good-0", 1, second_status),
    ]

    with pytest.raises(UsageError, match=r"ambiguous duplicate statuses.*fake-good-0"):
        successful_friend_ids_from_audit(rows, 1)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", ["fake-good-0"]),
        ("ok [orphans suspected]", ["fake-good-0"]),
        ("failed: exit 1", []),
    ],
)
def test_derivation_deduplicates_only_identical_statuses(status, expected):
    row = _friend_row("fake-good-0", 1, status)

    assert successful_friend_ids_from_audit([row, dict(row)], 1) == expected


def test_derivation_refuses_rows_with_nothing_for_the_pending_round(tmp_path):
    rows = [_friend_row("fake-good-0", 1, "ok")]

    with pytest.raises(UsageError, match=r"no rows for the pending critique round"):
        successful_friend_ids_from_audit(rows, 2)


def test_no_rows_at_all_derives_an_empty_quorum():
    """Distinct from rows that exist but skip the pending round: a run that
    has dispatched nothing has an empty quorum rather than an unreadable one."""
    assert successful_friend_ids_from_audit([], 1) == []
