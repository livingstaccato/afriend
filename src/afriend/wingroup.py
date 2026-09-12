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
guarantee than the POSIX pgid path, not merely a workaround for its absence.

There is also no SIGTERM-then-SIGKILL escalation here: `TerminateJobObject`
has no graceful mode, so there is nothing to escalate from. One call ends
the whole tree.
"""

import ctypes
from ctypes import wintypes
import sys

# Imported only on Windows (spawn.py, tests/test_wingroup.py). The assert
# also tells mypy to skip this module elsewhere, where ctypes has no WinDLL.
assert sys.platform == "win32"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# JOBOBJECTINFOCLASS values this module uses.
_JobObjectExtendedLimitInformation = 9
_JobObjectBasicProcessIdList = 3

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100

# Room for this many process IDs when checking whether a job is still
# occupied. A friend CLI's own tree (itself, an MCP server or two, maybe a
# shell) is nowhere near this; sized generously rather than exactly.
_MAX_TRACKED_PIDS = 256


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


def terminate(job_handle: int, exit_code: int = 1) -> bool:
    """Kill every process still in the job. Returns True if the job still
    reports a member afterward (orphan suspected) -- mirrors
    `procgroup._terminate_group`'s return contract, but there is no
    escalation window here: `TerminateJobObject` has no graceful mode, so
    one call is the whole of it, followed by one membership check rather
    than a poll loop, since Windows offers no intermediate state to wait
    through.
    """
    ctypes.set_last_error(0)
    if not _kernel32.TerminateJobObject(job_handle, exit_code):
        # ERROR_ACCESS_DENIED here has the same shape as procgroup's DENIED:
        # nothing was reaped, so report a suspected orphan rather than a
        # clean sweep.
        return True
    remaining = _assigned_process_count(job_handle)
    return remaining != 0


def close(job_handle: int) -> None:
    _kernel32.CloseHandle(job_handle)
