"""Inventory retained runs and remove only confirmed, safe terminal runs."""

import argparse
from collections.abc import Iterator
import contextlib
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any

from ..errors import UsageError
from ..jsonio import MAX_JSON_FILE_BYTES, decode_json_object
from ..runstore import default_root
from ..secureio import secure_open_directory, secure_open_read, secure_open_write, secure_read_bytes
from . import status

_TIMESTAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
_MODES = frozenset({"report", "crossexam", "gate", "loop"})
_ROOT_LOCK_NAME = ".afriend-runs-prune.lock"


def _root(out: str | None) -> Path:
    return (Path(out) if out else default_root()).absolute()


def _directory_names(root: Path) -> tuple[list[str], list[str]]:
    """List root children from an opened descriptor, never following a child."""
    try:
        descriptor = secure_open_directory(root, root=root)
    except FileNotFoundError:
        return [], []
    except OSError:
        return [], [f"cannot inspect run root {root}"]
    try:
        return sorted(os.listdir(descriptor)), []  # noqa: PTH208 -- descriptor avoids child races
    except OSError:
        return [], [f"cannot list run root {root}"]
    finally:
        os.close(descriptor)


def _metadata(run_dir: Path, *, root: Path) -> dict[str, Any]:
    payload = secure_read_bytes(run_dir / "run.json", root=root, max_bytes=MAX_JSON_FILE_BYTES)
    return decode_json_object(payload, path=run_dir / "run.json", label="saved run metadata")


def _optional_metadata(run_dir: Path, *, root: Path) -> dict[str, Any]:
    try:
        return _metadata(run_dir, root=root)
    except FileNotFoundError:
        return {}


def _parse_timestamp(value: object) -> tuple[str | None, datetime | None]:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None, None
    return value, parsed


def _timestamp(meta: dict[str, Any]) -> tuple[str | None, datetime | None]:
    finished = meta.get("finished_at")
    return _parse_timestamp(meta.get("started_at") if finished is None else finished)


def _finished_timestamp(meta: dict[str, Any]) -> tuple[str | None, datetime | None]:
    return _parse_timestamp(meta.get("finished_at"))


def _has_run_artifact(run_dir: Path, *, root: Path) -> bool:
    """Whether this directory warrants a warning if it cannot be summarized."""
    for name in ("run.json", "events.jsonl"):
        try:
            descriptor = secure_open_read(run_dir / name, root=root)
        except FileNotFoundError:
            continue
        except OSError:
            return True
        else:
            os.close(descriptor)
            return True
    return False


def _record(root: Path, name: str) -> dict[str, object] | None:
    """Build one deliberately small inventory row, or reject a non-run."""
    run_dir = root / name
    descriptor = secure_open_directory(run_dir, root=root)
    os.close(descriptor)
    if not _has_run_artifact(run_dir, root=root):
        return None
    summary = status.summarize(run_dir, root=root)
    meta = _optional_metadata(run_dir, root=root)
    timestamp, _parsed = _timestamp(meta)
    mode = summary.get("mode")
    scope = summary.get("scope")
    report = run_dir / "report.md"
    try:
        report_path: str | None = str(report) if _regular(report, root=root) else None
    except FileNotFoundError:
        report_path = None
    except OSError:
        raise UsageError("unsafe report artifact") from None
    return {
        "id": name,
        "path": str(run_dir),
        "state": summary["state"],
        "mode": mode if mode in _MODES else None,
        "scope": scope if scope in {"doc", "repo", "unknown"} else "unknown",
        "timestamp": timestamp,
        "report_path": report_path,
    }


def _regular(path: Path, *, root: Path) -> bool:
    descriptor = secure_open_read(path, root=root)
    os.close(descriptor)
    return True


def _inventory(root: Path) -> tuple[list[dict[str, object]], list[str]]:
    names, warnings = _directory_names(root)
    records: list[dict[str, object]] = []
    for name in names:
        if name == _ROOT_LOCK_NAME:
            continue
        try:
            record = _record(root, name)
        except (OSError, UsageError, ValueError, TypeError):
            warnings.append(f"skipped directory {name!r}: invalid or unreadable run artifacts")
            continue
        if record is not None:
            records.append(record)
    return records, warnings


def _lock_is_held(run_dir: Path, *, root: Path) -> bool:
    """Check an existing writer lock without creating or changing it."""
    try:
        descriptor = secure_open_read(run_dir / ".lock", root=root)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
    return False


def _eligible(record: dict[str, object], meta: dict[str, Any], *, cutoff: datetime) -> bool:
    """Keep age selection intentionally narrower than display inventory."""
    _shown, timestamp = _finished_timestamp(meta)
    mode = meta.get("mode")
    return (
        record["state"] == "terminal"
        and meta.get("lifecycle_state") == "terminal"
        and isinstance(mode, str)
        and mode in _MODES
        and timestamp is not None
        and timestamp < cutoff
    )


def _candidates(root: Path, *, older_than_days: int) -> tuple[list[dict[str, object]], list[str]]:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    records, warnings = _inventory(root)
    selected: list[dict[str, object]] = []
    for record in records:
        name = record["id"]
        assert isinstance(name, str)
        run_dir = root / name
        try:
            meta = _optional_metadata(run_dir, root=root)
            if _lock_is_held(run_dir, root=root):
                continue
        except (OSError, UsageError, ValueError, TypeError):
            warnings.append(f"skipped directory {name!r}: invalid or unreadable run artifacts")
            continue
        if _eligible(record, meta, cutoff=cutoff):
            selected.append(record)
    return selected, warnings


def prune_candidates(root: Path, *, older_than_days: int) -> list[dict[str, object]]:
    """Return safely selectable runs for callers that need a preview."""
    if older_than_days < 0:
        raise ValueError("older_than_days must be non-negative")
    return _candidates(root.absolute(), older_than_days=older_than_days)[0]


def _remove_tree(descriptor: int) -> None:
    """Unlink a run tree by file descriptor without ever traversing symlinks."""
    for entry in os.scandir(descriptor):
        try:
            info = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode):
            child = os.open(
                entry.name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                _remove_tree(child)
            finally:
                os.close(child)
            os.rmdir(entry.name, dir_fd=descriptor)
        else:
            os.unlink(entry.name, dir_fd=descriptor)


def _same_open_directory(parent: int, name: str, child: int) -> bool:
    """Ensure the directory name still identifies the descriptor we emptied."""
    expected = os.fstat(child)
    observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    return stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) == (
        expected.st_dev,
        expected.st_ino,
    )


def _staging_name(parent: int) -> str:
    """Create an empty, root-anchored directory for one atomic rename."""
    for _attempt in range(8):
        name = f".afriend-prune-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            continue
        return name
    raise OSError("could not reserve a unique prune staging directory")


def _stage_candidate(parent: int, name: str, child: int) -> str | None:
    """Move a named run once and return its verified staging name.

    The rename happens before recursive deletion.  If the staged directory's
    device/inode does not match the opened run descriptor, leave it intact as
    a safe-fail residue and do not traverse the opened run tree.
    """
    staging = _staging_name(parent)
    try:
        os.rename(name, staging, src_dir_fd=parent, dst_dir_fd=parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.rmdir(staging, dir_fd=parent)
        raise
    if not _same_open_directory(parent, staging, child):
        return None
    return staging


@contextlib.contextmanager
def _root_prune_lock(root: Path) -> Iterator[bool]:
    """Serialize prune revalidation and removal for this run root."""
    descriptor = secure_open_write(root / _ROOT_LOCK_NAME, root=root)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _delete(root: Path, record: dict[str, object], *, older_than_days: int) -> bool:
    """Revalidate and remove one candidate while holding its writer lock."""
    name = record["id"]
    assert isinstance(name, str)
    run_dir = root / name
    try:
        with _root_prune_lock(root) as holds_root_lock:
            if not holds_root_lock:
                return False
            try:
                descriptor = secure_open_write(run_dir / ".lock", root=root)
            except OSError:
                return False
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
                current = _record(root, name)
                if current is None:
                    return False
                meta = _metadata(run_dir, root=root)
                if not _eligible(current, meta, cutoff=cutoff):
                    return False
                run_descriptor = secure_open_directory(run_dir, root=root)
                try:
                    root_descriptor = secure_open_directory(root, root=root)
                    try:
                        staging = _stage_candidate(root_descriptor, name, run_descriptor)
                        if staging is None:
                            return False
                        _remove_tree(run_descriptor)
                        os.rmdir(staging, dir_fd=root_descriptor)
                        return True
                    finally:
                        os.close(root_descriptor)
                finally:
                    os.close(run_descriptor)
            except (OSError, UsageError, ValueError, TypeError):
                return False
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
    except (OSError, UsageError, ValueError, TypeError):
        return False


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"afriend runs: {warning}", file=sys.stderr)


def _render_rows(rows: list[dict[str, object]], *, action: str | None = None) -> str:
    if not rows:
        return ""
    prefix = f"{action}: " if action else ""
    return "\n".join(
        prefix
        + f"{row['id']} state={row['state']} mode={row['mode'] or 'unknown'} "
        + f"scope={row['scope']} timestamp={row['timestamp'] or 'unknown'} "
        + f"report={row['report_path'] or 'missing'}"
        for row in rows
    )


def cmd_runs(args: argparse.Namespace) -> int:
    root = _root(getattr(args, "out", None))
    if args.runs_command == "list":
        records, warnings = _inventory(root)
        if args.json:
            print(json.dumps({"runs": records, "warnings": warnings}, indent=2, sort_keys=True))
        else:
            output = _render_rows(records)
            if output:
                print(output)
        _print_warnings(warnings)
        return 0

    records, warnings = _candidates(root, older_than_days=args.older_than)
    pruned: list[dict[str, object]] = []
    if args.confirm:
        for record in records:
            if _delete(root, record, older_than_days=args.older_than):
                pruned.append(record)
            else:
                name = record["id"]
                warnings.append(
                    f"skipped directory {name!r}: changed, locked, or could not be removed"
                )
    if args.json:
        print(
            json.dumps(
                {
                    "candidates": records,
                    "preview": not args.confirm,
                    "pruned": pruned,
                    "warnings": warnings,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        output = _render_rows(
            pruned if args.confirm else records, action="pruned" if args.confirm else "would prune"
        )
        if output:
            print(output)
    _print_warnings(warnings)
    return 0
