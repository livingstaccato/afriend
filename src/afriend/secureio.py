"""Private filesystem primitives for run-owned artifacts.

Windows note: everything below the `_WINDOWS` split exists because Windows
has neither `dir_fd` (verified on this runtime: `os.supports_dir_fd` is
empty) nor `os.fchmod`, and cannot even open a bare directory as a file
descriptor at all (verified: `os.open(some_dir, os.O_RDONLY)` raises
`PermissionError` there). The POSIX functions below hold an open descriptor
to each directory as they walk down to a target, so a concurrent rename of a
traversed component cannot redirect a later step -- the kernel keeps
following the descriptor, not the name, resolving the whole
check-then-act race dir_fd exists to close.

Windows cannot do that at all, so its walk (`_win_reject_reparse`/`_win_walk`/
`_win_parent`) re-resolves each component by name and rejects anything that
looks like a symlink or an NTFS junction/mount point (`st_reparse_tag`,
which `os.path.islink()` alone misses -- verified: it does not flag a
junction) at each step. This narrows the race POSIX closes; it does not
close it. It is a stated, accepted trade-off (see AGENTS.md's platform
notes), not an oversight.

Windows also has nothing resembling POSIX file mode bits, so every `fchmod`/
`chmod(..., follow_symlinks=False)` call below is skipped there rather than
attempted -- attempting it raises `NotImplementedError` for the
`follow_symlinks=False` form specifically, verified on this runtime.
"""

from collections.abc import Iterator
import contextlib
import errno
import os
from pathlib import Path
import stat
import sys

_WINDOWS = sys.platform == "win32"

DIR_MODE = 0o700
FILE_MODE = 0o600

_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _relative_parts(root: Path, target: Path) -> tuple[str, ...]:
    """Return a lexical path below root without resolving any symlink."""
    anchor = Path(root).absolute()
    candidate = Path(target).absolute()
    try:
        relative = candidate.relative_to(anchor)
    except ValueError as exc:
        raise OSError(errno.EPERM, "secure path escapes its trusted root", str(target)) from exc
    if any(part in ("", ".", "..") for part in relative.parts):
        raise OSError(errno.EPERM, "invalid secure path component", str(target))
    return relative.parts


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("secure write made no progress")
        view = view[written:]


# ---------------------------------------------------------------------------
# POSIX: dir_fd-chained walk. Unused on Windows (guarded by _WINDOWS at each
# public call site), kept exactly as it was.
# ---------------------------------------------------------------------------


def _open_directory(name: str | Path, *, dir_fd: int | None = None) -> int:
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=dir_fd)
    try:
        info = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise OSError(errno.ENOTDIR, "secure path component is not a directory", str(name))
    return descriptor


@contextlib.contextmanager
def _directory_fd(
    root: Path,
    target: Path,
    *,
    create: bool = False,
    chmod_target: bool = False,
) -> Iterator[int]:
    """Open target beneath root while refusing every symlink component.

    Each component is opened relative to the already-open parent. Renaming a
    traversed directory and replacing its pathname with a symlink therefore
    cannot redirect a later operation: the kernel continues from the held
    descriptor rather than resolving the pathname again.
    """
    parts = _relative_parts(root, target)
    descriptor = _open_directory(Path(root).absolute())
    try:
        for part in parts:
            try:
                child = _open_directory(part, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, DIR_MODE, dir_fd=descriptor)
                child = _open_directory(part, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if chmod_target:
            os.fchmod(descriptor, DIR_MODE)
        yield descriptor
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _parent_fd(root: Path, target: Path) -> Iterator[tuple[int, str]]:
    parts = _relative_parts(root, target)
    if not parts:
        raise OSError(errno.EISDIR, "secure file path names a directory", str(target))
    parent = Path(root).absolute().joinpath(*parts[:-1])
    with _directory_fd(root, parent) as descriptor:
        yield descriptor, parts[-1]


# ---------------------------------------------------------------------------
# Windows: name-based walk. No dir_fd exists to chain through -- see the
# module docstring for what that costs.
# ---------------------------------------------------------------------------


def _win_reject_reparse(path: Path) -> None:
    """Refuse an existing symlink or NTFS junction/mount point at `path`.

    `os.path.islink()` alone does not flag a junction on Windows (verified);
    `st_reparse_tag` catches both. A path that does not exist yet is fine --
    there is nothing there to have been substituted.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0):
        raise OSError(
            errno.ELOOP, "secure path component is a symlink or reparse point", str(path)
        )


def _win_walk(root: Path, target: Path, *, create: bool = False) -> Path:
    """Windows analogue of `_directory_fd`: returns a validated absolute
    Path, since there is no descriptor to hand back instead."""
    parts = _relative_parts(root, target)
    current = Path(root).absolute()
    if not current.exists():
        # Distinguished from "exists but isn't a directory" below: callers
        # (e.g. commands/status.py's find_run) pattern-match on
        # FileNotFoundError specifically to report a friendly "no such run"
        # rather than a raw OSError -- found when that message silently
        # stopped appearing on Windows for a root that was simply never
        # created, and this check hadn't drawn the same distinction the loop
        # below already does for every component after the first.
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(current))
    _win_reject_reparse(current)
    if not current.is_dir():
        raise OSError(errno.ENOTDIR, "secure path component is not a directory", str(current))
    for part in parts:
        current = current / part
        if not current.exists():
            if not create:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(current))
            os.mkdir(current, DIR_MODE)
        _win_reject_reparse(current)
        if not current.is_dir():
            raise OSError(errno.ENOTDIR, "secure path component is not a directory", str(current))
    return current


def _win_parent(root: Path, target: Path) -> tuple[Path, str]:
    parts = _relative_parts(root, target)
    if not parts:
        raise OSError(errno.EISDIR, "secure file path names a directory", str(target))
    parent = Path(root).absolute().joinpath(*parts[:-1])
    return _win_walk(root, parent, create=False), parts[-1]


def _win_open_in_parent(anchor: Path, target: Path, flags: int, mode: int = FILE_MODE) -> int:
    """Open `target` via its validated parent. Best-effort: refuses an
    existing reparse point at the target first, but -- unlike the POSIX
    dir_fd path -- there is a real gap between that check and the
    `os.open()` call below where the filesystem could change underneath us.
    See the module docstring's Windows note.

    `os.O_BINARY` is mandatory here, not optional. Windows' `os.open()`
    opens in CRT TEXT mode by default, which makes `os.write()` translate
    every `\\n` byte to `\\r\\n` -- verified live: writing content that
    already contained `\\r\\n` came back as `\\r\\r\\n`, corrupting every
    payload this module writes on Windows (prompts, `run.json`, the ledger,
    a frozen artifact copy) the moment it contained a single CRLF line
    ending, which is the Windows-native default for a file saved by
    Notepad or any CRLF-configured editor.
    """
    parent_dir, name = _win_parent(anchor, target)
    final = parent_dir / name
    _win_reject_reparse(final)
    return os.open(final, flags | os.O_BINARY, mode)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def secure_mkdir(
    path: Path,
    *,
    parents: bool = False,
    exist_ok: bool = False,
    root: Path | None = None,
) -> Path:
    target = Path(path)
    if root is not None:
        if _WINDOWS:
            parts = _relative_parts(root, target)
            if not parts:
                _win_reject_reparse(target)
                if not target.is_dir():
                    raise OSError(
                        errno.ENOTDIR, "secure path component is not a directory", str(target)
                    )
                return target
            parent = Path(root).absolute().joinpath(*parts[:-1])
            parent_dir = _win_walk(root, parent, create=parents)
            final = parent_dir / parts[-1]
            try:
                os.mkdir(final, DIR_MODE)
            except FileExistsError:
                if not exist_ok:
                    raise
            _win_reject_reparse(final)
            if not final.is_dir():
                raise OSError(
                    errno.ENOTDIR, "secure path component is not a directory", str(final)
                )
            return target
        parts = _relative_parts(root, target)
        if not parts:
            with _directory_fd(root, target, chmod_target=True):
                return target
        parent = Path(root).absolute().joinpath(*parts[:-1])
        with _directory_fd(root, parent, create=parents) as descriptor:
            try:
                os.mkdir(parts[-1], DIR_MODE, dir_fd=descriptor)
            except FileExistsError:
                if not exist_ok:
                    raise
            child = _open_directory(parts[-1], dir_fd=descriptor)
            try:
                os.fchmod(child, DIR_MODE)
            finally:
                os.close(child)
        return target
    target.mkdir(mode=DIR_MODE, parents=parents, exist_ok=exist_ok)
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise OSError(errno.ELOOP, "secure directory must not be a symlink", str(target))
    if not _WINDOWS:
        target.chmod(DIR_MODE, follow_symlinks=False)
    return target


def secure_init_root(path: Path) -> Path:
    """Open or create a storage root without changing caller-owned modes.

    Existing path components are validation boundaries, not run-owned data.
    Walk them by descriptor (POSIX) or by re-validated name (Windows) so a
    concurrent symlink/junction swap cannot redirect root creation. Only
    components created by this call are forced private -- on POSIX; Windows
    has no equivalent private mode to force (see the module docstring).
    """
    target = Path(path).absolute()
    if _WINDOWS:
        anchor = Path(target.anchor)
        if not anchor.is_dir():
            raise OSError(errno.ENOTDIR, "secure path component is not a directory", str(anchor))
        current = anchor
        for part in target.parts[1:]:
            current = current / part
            if not current.exists():
                os.mkdir(current, DIR_MODE)
            _win_reject_reparse(current)
            if not current.is_dir():
                raise OSError(
                    errno.ENOTDIR, "secure path component is not a directory", str(current)
                )
        return target
    anchor = Path(target.anchor)
    parts = target.parts[1:]
    descriptor = _open_directory(anchor)
    try:
        for part in parts:
            created = False
            try:
                child = _open_directory(part, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, DIR_MODE, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                child = _open_directory(part, dir_fd=descriptor)
            if created:
                os.fchmod(child, DIR_MODE)
            os.close(descriptor)
            descriptor = child
    finally:
        os.close(descriptor)
    return target


def secure_write_bytes(path: Path, payload: bytes, *, root: Path | None = None) -> Path:
    target = Path(path)
    anchor = target.parent if root is None else root
    if _WINDOWS:
        descriptor = _win_open_in_parent(anchor, target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return target
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _parent_fd(anchor, target) as parent:
        descriptor = os.open(parent[1], flags, FILE_MODE, dir_fd=parent[0])
        try:
            os.fchmod(descriptor, FILE_MODE)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return target


def secure_open_write(path: Path, *, root: Path) -> int:
    """Open a private file for replacement while holding its safe parent."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if _WINDOWS:
        return _win_open_in_parent(root, path, flags)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _parent_fd(root, path) as (parent, name):
        descriptor = os.open(name, flags, FILE_MODE, dir_fd=parent)
    try:
        os.fchmod(descriptor, FILE_MODE)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def secure_open_append(path: Path, *, root: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if _WINDOWS:
        return _win_open_in_parent(root, path, flags)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _parent_fd(root, path) as (parent, name):
        descriptor = os.open(name, flags, FILE_MODE, dir_fd=parent)
    try:
        os.fchmod(descriptor, FILE_MODE)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def secure_open_read(path: Path, *, root: Path) -> int:
    if _WINDOWS:
        parent_dir, name = _win_parent(root, path)
        final = parent_dir / name
        _win_reject_reparse(final)
        # O_BINARY, or Windows' CRT text-mode read silently strips every \r
        # before this module's caller ever sees the bytes -- fatal for
        # anything hashed (secure_read_bytes/artifact_copy) or byte-length
        # checked, and wrong even for a caller expecting text, which should
        # get exactly one well-defined newline translation (Python's own
        # universal-newline handling), not a second, hidden one underneath it.
        descriptor = os.open(final, os.O_RDONLY | os.O_BINARY)
    else:
        with _parent_fd(root, path) as (parent, name):
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
    try:
        info = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise OSError(errno.ELOOP, "secure file must be regular", str(path))
    return descriptor


def secure_read_bytes(path: Path, *, root: Path, max_bytes: int) -> bytes:
    descriptor = secure_open_read(path, root=root)
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise OSError(errno.EFBIG, "secure file exceeds byte limit", str(path))
        return payload
    finally:
        os.close(descriptor)


def secure_regular_exists(path: Path, *, root: Path) -> bool:
    try:
        descriptor = secure_open_read(path, root=root)
    except FileNotFoundError:
        return False
    else:
        os.close(descriptor)
        return True


def secure_create_bytes(path: Path, payload: bytes, *, root: Path) -> Path:
    """Durably create one private file without replacing an existing name."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if _WINDOWS:
        descriptor = _win_open_in_parent(root, path, flags)
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return Path(path)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _parent_fd(root, path) as (parent, name):
        descriptor = os.open(name, flags, FILE_MODE, dir_fd=parent)
        try:
            os.fchmod(descriptor, FILE_MODE)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return Path(path)


def secure_open_directory(path: Path, *, root: Path) -> int:
    """Return a descriptor for an existing directory below root.

    POSIX only. Windows cannot open a bare directory as a file descriptor at
    all (verified: `os.open(some_dir, os.O_RDONLY)` raises `PermissionError`
    there), so this raises there rather than pretending to succeed. Callers
    that only need to validate a directory or fsync it for durability should
    use `secure_validate_directory`/`secure_sync_directory` instead, which
    have a real Windows implementation; this remains for the one caller
    (`commands/runs.py`'s prune machinery) that needs a genuine dir_fd to
    chain further POSIX-only operations through, and is POSIX-only itself.
    """
    if _WINDOWS:
        raise OSError(
            errno.ENOSYS,
            "directory file descriptors are not available on Windows",
            str(path),
        )
    parts = _relative_parts(root, path)
    descriptor = _open_directory(Path(root).absolute())
    try:
        for part in parts:
            child = _open_directory(part, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def secure_validate_directory(path: Path, *, root: Path) -> None:
    """Confirm `path` exists, is a real directory, and is safely reachable
    from `root`, without asserting anything further about it. Replaces the
    open-then-immediately-close idiom callers used to spell with
    `secure_open_directory`, which Windows cannot perform (see its
    docstring)."""
    if _WINDOWS:
        _win_walk(root, Path(path), create=False)
        return
    descriptor = secure_open_directory(path, root=root)
    os.close(descriptor)


def secure_sync_directory(path: Path, *, root: Path) -> None:
    """Best-effort fsync of a directory's own metadata, so a rename or
    create inside it is durable across a crash, not just visible to a
    process that has not crashed.

    Windows has no file descriptor for a directory at all (see
    `secure_open_directory`'s docstring), so there is no call to make here --
    this is a documented no-op on Windows rather than a raised error, relying
    instead on NTFS's own journaling. It is a real, accepted narrowing of the
    durability guarantee versus POSIX, not an oversight.
    """
    if _WINDOWS:
        _win_walk(root, Path(path), create=False)
        return
    descriptor = secure_open_directory(path, root=root)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def secure_write_text(path: Path, text: str, *, root: Path | None = None) -> Path:
    return secure_write_bytes(path, text.encode("utf-8"), root=root)


def secure_copy(source: Path, target: Path, *, root: Path | None = None) -> Path:
    destination = Path(target)
    anchor = destination.parent if root is None else root
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if _WINDOWS:
        descriptor = _win_open_in_parent(anchor, destination, flags)
        try:
            with Path(source).open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    _write_all(descriptor, chunk)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return destination
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _parent_fd(anchor, destination) as parent:
        descriptor = os.open(parent[1], flags, FILE_MODE, dir_fd=parent[0])
        try:
            os.fchmod(descriptor, FILE_MODE)
            with Path(source).open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    _write_all(descriptor, chunk)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return destination


def secure_replace(source: Path, target: Path, *, root: Path) -> Path:
    """Atomically replace target without resolving either parent by name."""
    source_path = Path(source)
    target_path = Path(target)
    if source_path.parent != target_path.parent:
        raise OSError(errno.EXDEV, "secure replacement requires one directory")
    if _WINDOWS:
        parent_dir, source_name = _win_parent(root, source_path)
        os.replace(parent_dir / source_name, parent_dir / target_path.name)
        return Path(target)
    with _parent_fd(root, source_path) as (parent, source_name):
        os.replace(source_name, target_path.name, src_dir_fd=parent, dst_dir_fd=parent)
    return Path(target)


def secure_unlink(path: Path, *, root: Path, missing_ok: bool = False) -> None:
    if _WINDOWS:
        parent_dir, name = _win_parent(root, path)
        try:
            os.unlink(parent_dir / name)
        except FileNotFoundError:
            if not missing_ok:
                raise
        return
    with _parent_fd(root, path) as (descriptor, name):
        try:
            os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            if not missing_ok:
                raise


def secure_read_text(path: Path, *, root: Path) -> str:
    if _WINDOWS:
        parent_dir, name = _win_parent(root, path)
        final = parent_dir / name
        _win_reject_reparse(final)
        # O_BINARY: the fdopen("r", ...) below already does one well-defined
        # universal-newline translation; without this the raw fd would do
        # a second, hidden one underneath it at the CRT level first.
        descriptor = os.open(final, os.O_RDONLY | os.O_BINARY)
    else:
        with _parent_fd(root, path) as (parent, name):
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.ELOOP, "secure file must be regular", str(path))
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def repair_private(path: Path, *, directory: bool = False) -> None:
    """Repair one known run-owned path without following a symlink."""
    target = Path(path)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return
    expected = stat.S_IFDIR if directory else stat.S_IFREG
    if stat.S_IFMT(info.st_mode) != expected:
        raise OSError(errno.ELOOP, "run-owned path has unsafe file type", str(target))
    if not _WINDOWS:
        target.chmod(DIR_MODE if directory else FILE_MODE, follow_symlinks=False)


def repair_private_tree(root: Path) -> None:
    """Repair a validated run tree without following any contained symlink."""
    base = Path(root)

    if _WINDOWS:

        def repair_windows(directory: Path) -> None:
            for entry in os.scandir(directory):
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    repair_windows(Path(entry.path))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise OSError(errno.ELOOP, "run-owned path has unsafe file type", entry.path)
                # No mode bits worth restoring on Windows -- presence and
                # type are what this repairs there. See the module docstring.

        repair_windows(base)
        return

    def repair(descriptor: int, display: Path) -> None:
        os.fchmod(descriptor, DIR_MODE)
        for name in os.listdir(descriptor):
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            child_display = display / name
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                child = _open_directory(name, dir_fd=descriptor)
                try:
                    repair(child, child_display)
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise OSError(
                    errno.ELOOP, "run-owned path has unsafe file type", str(child_display)
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            child = os.open(name, flags, dir_fd=descriptor)
            try:
                mode = 0o700 if info.st_mode & 0o111 else FILE_MODE
                os.fchmod(child, mode)
            finally:
                os.close(child)

    with _directory_fd(base.parent, base) as root_descriptor:
        repair(root_descriptor, base)
