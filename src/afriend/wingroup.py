"""Reaping a friend's whole process tree on Windows, via Job Objects.

POSIX process groups (`procgroup.py`) have no Windows equivalent: there is
no `os.killpg`, no pgid. The nearest analogue is a Job Object -- assign a
process to one at spawn time, and `TerminateJobObject` kills every process
still in it in one call, the same role `SIGKILL` to the group plays on
POSIX.

Built on raw `ctypes` calls into `kernel32.dll` rather than `pywin32`, so
Windows support does not cost this project's stdlib-only, zero-runtime-
dependency guarantee -- see the design discussion in AGENTS.md.

**A descendant cannot normally escape this job**, unlike POSIX
`os.setsid()` escape (see `procgroup.py`'s module docstring and
`test_setsid_escapee_is_not_reaped`): escaping a job requires the process
that spawns the descendant to pass `CREATE_BREAKAWAY_FROM_JOB`, and the
kernel refuses that unless the job was created with
`JOB_OBJECT_LIMIT_BREAKAWAY_OK` or `..._SILENT_BREAKAWAY_OK` set on it,
which this module never sets. This is a strictly stronger containment
guarantee than the POSIX pgid path, not merely a workaround for its absence
-- but only once the target process is actually a job member. `assign`
below only pulls in a process's FUTURE descendants; a process created and
immediately resumed the ordinary way can spawn a child of its own before
its caller finishes `OpenProcess`+`AssignProcessToJobObject`, and that
child is never a member. `spawn.py` closes this window by creating the
process with `CREATE_SUSPENDED` (via `Popen(creationflags=...)`) and calling
`resume` here only after `assign` has been attempted: the target's main
thread has not executed a single instruction before that point, so nothing
it might spawn can exist yet.

There is also no SIGTERM-then-SIGKILL escalation here: `TerminateJobObject`
has no graceful mode, so there is nothing to escalate from. One call ends
the whole tree. Termination is not instantaneous, though: Windows initiates
it synchronously but a member's rundown (closing handles, unloading DLLs)
completes asynchronously, so `terminate` polls job membership for up to
`grace_seconds` rather than checking once immediately -- mirroring
`procgroup._reap_after_signal`'s wait-then-check ordering, not a single
racy snapshot.
"""

import ctypes
from ctypes import wintypes
import subprocess
import sys
import time

from . import execresolve

# Imported only on Windows (spawn.py, tests/test_wingroup.py). The assert
# also tells mypy to skip this module elsewhere, where ctypes has no WinDLL.
assert sys.platform == "win32"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# NtResumeProcess is undocumented but stable (used by Chromium and other
# sandboxes to resume a CREATE_SUSPENDED process by process handle alone).
# Needed because subprocess.Popen closes its own thread handle immediately
# after CreateProcess returns (see CPython's _execute_child), so by the time
# this module runs there is no thread handle left to call ResumeThread on.
_ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

# JOBOBJECTINFOCLASS values this module uses.
_JobObjectExtendedLimitInformation = 9
_JobObjectBasicProcessIdList = 3

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800

# Created with subprocess.Popen(creationflags=wingroup.CREATE_SUSPENDED | ...)
# so the caller can assign the process to a job before it runs a single
# instruction of its own -- see the module docstring. Not exposed by the
# stdlib `subprocess` module (unlike CREATE_NEW_PROCESS_GROUP), so it is
# defined here instead of assumed to exist on it.
CREATE_SUSPENDED = 0x00000004

# Room for this many process IDs when checking whether a job is still
# occupied. A friend CLI's own tree (itself, an MCP server or two, maybe a
# shell) is nowhere near this; sized generously rather than exactly.
_MAX_TRACKED_PIDS = 256

# How often `terminate` re-checks job membership while waiting for a member's
# asynchronous rundown to finish. Matches procgroup.py's own poll cadence.
_POLL_INTERVAL_S = 0.05
# Default wait for terminate()'s post-kill membership poll; spawn.py passes
# its own KILL_GRACE_SECONDS explicitly so both platforms share one constant,
# this is only the fallback for a caller that does not.
_DEFAULT_GRACE_SECONDS = 5.0

# taskkill's documented exit code for "no process with that PID exists" --
# the ordinary case when `taskkill_tree`'s target already exited (or, for a
# process that could never be resumed after being created suspended, never
# ran at all) before the call ran. Treated as a clean no-op, not a suspected
# orphan.
_TASKKILL_PROCESS_NOT_FOUND = 128


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wintypes.DWORD),
        ("NumberOfProcessIdsInList", wintypes.DWORD),
        ("ProcessIdList", ctypes.c_size_t * _MAX_TRACKED_PIDS),
    ]


_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE

_kernel32.SetInformationJobObject.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL

_kernel32.QueryInformationJobObject.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryInformationJobObject.restype = wintypes.BOOL

_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE

_kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateJobObject.restype = wintypes.BOOL

_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

# NTSTATUS, not a Win32 BOOL -- 0 (STATUS_SUCCESS) means it worked; anything
# else is an NTSTATUS code, not something GetLastError() can decode.
_ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
_ntdll.NtResumeProcess.restype = ctypes.c_uint32


def _win_error(action: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), f"{action} failed")


def create_job() -> int:
    """Create a Job Object that kills every member if this handle is ever
    closed without an explicit terminate -- a safety net, not the primary
    kill path (see `terminate`)."""
    ctypes.set_last_error(0)
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise _win_error("CreateJobObjectW")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ctypes.set_last_error(0)
    ok = _kernel32.SetInformationJobObject(
        handle,
        _JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        error = _win_error("SetInformationJobObject")
        _kernel32.CloseHandle(handle)
        raise error
    return int(handle)


def assign(job_handle: int, pid: int) -> None:
    """Put process `pid` under `job_handle`'s control.

    Must be called immediately after the process is spawned, before it can
    spawn anything of its own -- a process assigned to a job only pulls its
    FUTURE descendants in with it; nothing spawned before assignment is
    covered.
    """
    ctypes.set_last_error(0)
    process = _kernel32.OpenProcess(_PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, pid)
    if not process:
        raise _win_error(f"OpenProcess({pid})")
    try:
        ctypes.set_last_error(0)
        if not _kernel32.AssignProcessToJobObject(job_handle, process):
            raise _win_error(f"AssignProcessToJobObject({pid})")
    finally:
        _kernel32.CloseHandle(process)


def resume(pid: int) -> None:
    """Resume a process created with `CREATE_SUSPENDED`.

    Call this only after `assign` has been attempted (successfully or not)
    on the same pid -- see the module docstring. Resumes by process handle
    via `NtResumeProcess` rather than by thread handle: `subprocess.Popen`
    closes the thread handle `CreateProcess` returned before this module
    ever sees it, so there is nothing to call `ResumeThread` on by the time
    a caller here could reach it.
    """
    ctypes.set_last_error(0)
    process = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not process:
        raise _win_error(f"OpenProcess({pid})")
    try:
        status = _ntdll.NtResumeProcess(process)
        if status != 0:
            raise OSError(f"NtResumeProcess({pid}) failed with NTSTATUS 0x{status:08X}")
    finally:
        _kernel32.CloseHandle(process)


def _assigned_process_count(job_handle: int) -> int:
    """Best-effort count of processes still in the job. Used only to decide
    `orphans_suspected`, so an error here is treated as "cannot tell" (kept
    as suspected) rather than raised."""
    info = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
    needed = wintypes.DWORD(0)
    ok = _kernel32.QueryInformationJobObject(
        job_handle,
        _JobObjectBasicProcessIdList,
        ctypes.byref(info),
        ctypes.sizeof(info),
        ctypes.byref(needed),
    )
    if not ok:
        return -1
    return int(info.NumberOfAssignedProcesses)


def terminate(
    job_handle: int, exit_code: int = 1, *, grace_seconds: float = _DEFAULT_GRACE_SECONDS
) -> bool:
    """Kill every process still in the job. Returns True if the job still
    reports a member after up to `grace_seconds` (orphan suspected) --
    mirrors `procgroup._terminate_group`'s return contract. There is no
    SIGTERM-then-SIGKILL escalation here: `TerminateJobObject` has no
    graceful mode, so one call ends the whole tree. But that call only
    *initiates* termination -- a member's rundown completes asynchronously,
    so this polls membership for up to `grace_seconds` rather than checking
    once immediately after the call returns, the same ordering
    `procgroup._reap_after_signal` uses (wait, then check), not a single
    racy snapshot taken before rundown can plausibly have finished.
    """
    ctypes.set_last_error(0)
    if not _kernel32.TerminateJobObject(job_handle, exit_code):
        # ERROR_ACCESS_DENIED here has the same shape as procgroup's DENIED:
        # nothing was reaped, so report a suspected orphan rather than a
        # clean sweep.
        return True
    deadline = time.monotonic() + grace_seconds
    remaining = _assigned_process_count(job_handle)
    while remaining != 0 and time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        remaining = _assigned_process_count(job_handle)
    return remaining != 0


def close(job_handle: int) -> None:
    _kernel32.CloseHandle(job_handle)


def taskkill_tree(pid: int, *, timeout: float) -> bool:
    """Best-effort tree-kill via `taskkill /PID <pid> /T /F`, for a process
    this module could not (or must not) track with a Job Object: Job Object
    setup itself failed, or a process created suspended could not be resumed
    -- in both cases there is no job to call `terminate` on. Callers that
    already have one should call `terminate` instead; this exists precisely
    for the cases where they don't.

    Bounded like every other wait in the spawn path: taskkill shells out to
    RPC/WMI paths that can themselves hang on an unhealthy machine, the same
    class of condition that broke Job Object setup or process resumption in
    the first place.

    Returns True if the outcome should be treated as a suspected orphan --
    the call itself failing to start or timing out, or a nonzero exit that
    is not taskkill's own documented "no such process" code (128, the
    ordinary case when the target had already exited, or never ran at all).
    """
    try:
        result = subprocess.run(
            [execresolve.taskkill_executable(), "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return result.returncode not in (0, _TASKKILL_PROCESS_NOT_FOUND)
