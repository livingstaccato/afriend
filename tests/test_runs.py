"""Inventory and guarded pruning of retained afriend run directories."""

import json
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="afriend runs prune is POSIX-only for now -- its deletion "
    "machinery uses dir_fd operations directly (commands/runs.py), which "
    "Windows does not support; see AGENTS.md's platform notes",
)

if sys.platform != "win32":
    import fcntl

from afriend import cli, cliargs
from afriend.commands import runs
from afriend.events import EventRecord


def _terminal_run(
    root: Path,
    name: str,
    *,
    finished_at: str = "2000-01-01T00:00:00Z",
) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": "terminal",
                "mode": "report",
                "finished_at": finished_at,
            }
        ),
        encoding="utf-8",
    )
    (run / "report.md").write_text("# report\n", encoding="utf-8")
    return run


def _live_run(root: Path, name: str) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps({"lifecycle_state": "running", "mode": "report"}), encoding="utf-8"
    )
    return run


def test_runs_parser_registers_list_and_prune_commands():
    parser = cliargs.build_parser()

    listed = parser.parse_args(["runs", "list", "--out", "/tmp/runs", "--json"])
    pruned = parser.parse_args(
        ["runs", "prune", "--older-than", "0", "--out", "/tmp/runs", "--confirm"]
    )

    assert (listed.command, listed.runs_command, listed.json) == ("runs", "list", True)
    assert (pruned.command, pruned.runs_command, pruned.older_than, pruned.confirm) == (
        "runs",
        "prune",
        0,
        True,
    )


@pytest.mark.parametrize("value", ["-1", "1.5", "days", "", "999999999999"])
def test_runs_prune_rejects_non_whole_or_negative_day_ages(value):
    with pytest.raises(SystemExit) as exc_info:
        cliargs.build_parser().parse_args(["runs", "prune", "--older-than", value])

    assert exc_info.value.code == 2


def test_list_only_reports_valid_direct_child_runs(tmp_path, capsys):
    root = tmp_path / "runs"
    done = _terminal_run(root, "done")
    (root / "not-a-run").mkdir()
    (root / "malformed").mkdir()
    (root / "malformed" / "run.json").write_text("not json", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    assert cli.main(["runs", "list", "--out", str(root)]) == 0

    output = capsys.readouterr()
    assert "done state=terminal" in output.out
    assert str(done / "report.md") in output.out
    assert "not-a-run" not in output.out
    assert "malformed" in output.err
    assert "escape" in output.err


def test_list_json_projects_only_safe_inventory_fields(tmp_path, capsys):
    root = tmp_path / "runs"
    done = _terminal_run(root, "done")

    assert cli.main(["runs", "list", "--out", str(root), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["warnings"] == []
    assert payload["runs"] == [
        {
            "id": "done",
            "mode": "report",
            "path": str(done),
            "report_path": str(done / "report.md"),
            "scope": "unknown",
            "state": "terminal",
            "timestamp": "2000-01-01T00:00:00Z",
        }
    ]


def test_list_treats_a_missing_root_as_an_empty_inventory(tmp_path, capsys):
    missing = tmp_path / "missing"

    assert cli.main(["runs", "list", "--out", str(missing), "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == {"runs": [], "warnings": []}


def test_list_keeps_reportless_and_event_only_runs(tmp_path, capsys):
    root = tmp_path / "runs"
    reportless = _terminal_run(root, "reportless")
    (reportless / "report.md").unlink()
    event_only = root / "event-only"
    event_only.mkdir()
    event_only_event = EventRecord.create(
        "run_started",
        {"mode": "report", "profile": "quick", "status": "started", "scope": "doc"},
        run_id="event-only",
        timestamp="2000-01-01T00:00:00Z",
    )
    (event_only / "events.jsonl").write_text(
        json.dumps(event_only_event.to_dict()) + "\n", encoding="utf-8"
    )

    assert cli.main(["runs", "list", "--out", str(root), "--json"]) == 0

    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)["runs"]}
    assert rows["reportless"]["report_path"] is None
    assert rows["event-only"] == {
        "id": "event-only",
        "mode": "report",
        "path": str(event_only),
        "report_path": None,
        "scope": "doc",
        "state": "live",
        "timestamp": None,
    }


def test_list_uses_started_at_when_finished_at_is_null(tmp_path, capsys):
    root = tmp_path / "runs"
    run = root / "in-progress"
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": "running",
                "mode": "report",
                "finished_at": None,
                "started_at": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["runs", "list", "--out", str(root), "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["runs"][0]["timestamp"] == "2000-01-01T00:00:00Z"


def test_prune_is_a_preview_until_confirmed(tmp_path, capsys):
    root = tmp_path / "runs"
    old = _terminal_run(root, "old")

    assert cli.main(["runs", "prune", "--older-than", "1", "--out", str(root), "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["preview"] is True
    assert [entry["id"] for entry in preview["candidates"]] == ["old"]
    assert old.exists()

    assert (
        cli.main(["runs", "prune", "--older-than", "1", "--confirm", "--out", str(root), "--json"])
        == 0
    )
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["preview"] is False
    assert [entry["id"] for entry in confirmed["pruned"]] == ["old"]
    assert not old.exists()


def test_prune_never_selects_live_locked_or_symlink_entries(tmp_path, capsys):
    root = tmp_path / "runs"
    _live_run(root, "live")
    locked = _terminal_run(root, "locked")
    lock = (locked / ".lock").open("w", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    try:
        assert cli.main(["runs", "prune", "--older-than", "0", "--out", str(root), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["candidates"] == []
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_prune_excludes_malformed_and_nonrun_entries(tmp_path, capsys):
    root = tmp_path / "runs"
    _terminal_run(root, "old")
    malformed = root / "malformed"
    malformed.mkdir()
    (malformed / "run.json").write_text("{", encoding="utf-8")
    (root / "plain-file").write_text("not a directory", encoding="utf-8")

    assert cli.main(["runs", "prune", "--older-than", "0", "--out", str(root), "--json"]) == 0
    assert [entry["id"] for entry in json.loads(capsys.readouterr().out)["candidates"]] == ["old"]


def test_prune_rejects_terminal_metadata_with_an_invalid_mode(tmp_path, capsys):
    root = tmp_path / "runs"
    malformed = _terminal_run(root, "malformed")
    (malformed / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": "terminal",
                "finished_at": "2000-01-01T00:00:00Z",
                "mode": ["invalid"],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(["runs", "prune", "--older-than", "1", "--confirm", "--out", str(root), "--json"])
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == []
    assert payload["pruned"] == []
    assert malformed.exists()


def test_prune_requires_a_terminal_finished_timestamp(tmp_path, capsys):
    root = tmp_path / "runs"
    malformed = _terminal_run(root, "missing-finish")
    (malformed / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": "terminal",
                "mode": "report",
                "started_at": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["runs", "prune", "--older-than", "1", "--out", str(root), "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["candidates"] == []
    assert malformed.exists()


def test_prune_preserves_a_replacement_detected_after_staging(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _terminal_run(root, "old")
    candidate = runs.prune_candidates(root, older_than_days=1)[0]
    original = root / "old-original"
    real_check = runs._same_open_directory
    replacement_identity: tuple[int, int] | None = None

    def replace_after_check(parent: int, name: str, child: int) -> bool:
        nonlocal replacement_identity
        assert replacement_identity is None
        assert real_check(parent, name, child)
        (root / name).rename(original)
        (root / name).mkdir()
        created = (root / name).stat()
        replacement_identity = (created.st_dev, created.st_ino)
        return real_check(parent, name, child)

    monkeypatch.setattr(runs, "_same_open_directory", replace_after_check)

    assert not runs._delete(root, candidate, older_than_days=1)
    assert replacement_identity is not None
    assert (original / "report.md").is_file()
    assert any(
        (entry.stat().st_dev, entry.stat().st_ino) == replacement_identity
        for entry in root.iterdir()
    )


def test_prune_refuses_an_unsafe_root_lock_without_deleting_a_run(tmp_path):
    root = tmp_path / "runs"
    run = _terminal_run(root, "old")
    candidate = runs.prune_candidates(root, older_than_days=1)[0]
    (root / runs._ROOT_LOCK_NAME).symlink_to(tmp_path / "outside")

    assert not runs._delete(root, candidate, older_than_days=1)
    assert run.is_dir()
