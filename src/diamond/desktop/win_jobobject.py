"""Windows Job Object wrapper — guarantee child processes die with us.

Without this, a hard-killed launcher (Task Manager / power loss /
PyInstaller crash before atexit hooks fire) leaves uvicorn + node
running in the background, holding TCP ports and DuckDB locks. The
next launch then fails to bind and the user has to ``kill-stale.bat``.

Job Objects are the bulletproof Windows primitive for "kill this
group of processes when the parent exits". We:

    1. Create a Job Object (anonymous handle).
    2. Set ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` via
       ``SetInformationJobObject``. The OS then closes the job — and
       every assigned process — when the last handle to it goes
       away.
    3. Assign each spawned ``subprocess.Popen`` PID to the job via
       ``AssignProcessToJobObject`` (called from ``sidecar.py``).

The handle is held in module-level state for the lifetime of the
launcher. We deliberately don't ``CloseHandle`` until process exit —
the OS does it for us, and an early close would defeat the entire
point.

References:
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/
- https://stackoverflow.com/a/23587108  (the canonical Python recipe)
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Optional

log = logging.getLogger(__name__)

# Module-level: keeps the handle alive past create_kill_on_close_job's
# return. Closing this handle (or letting GC do it) terminates every
# process in the job — that's exactly what we want at launcher exit.
_JOB_HANDLE: Optional[int] = None


# ---- Win32 types & constants -----------------------------------------------

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


# ---- Public API -------------------------------------------------------------


def create_kill_on_close_job() -> int:
    """Create a Job Object whose closure kills every assigned process.

    Returns the raw handle (an integer). The handle is also stashed
    in module-level state so it stays alive for the launcher's
    lifetime — the OS auto-cleans on process exit.

    Raises ``OSError`` on Win32 failure (rare; usually means a
    sandbox / restricted-token environment).
    """
    if sys.platform != "win32":
        raise OSError("Job Objects are Windows-only")

    global _JOB_HANDLE
    if _JOB_HANDLE is not None:
        return _JOB_HANDLE

    k32 = _kernel32()
    k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE

    handle = k32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    k32.SetInformationJobObject.restype = wintypes.BOOL

    ok = k32.SetInformationJobObject(
        handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        err = ctypes.get_last_error()
        k32.CloseHandle(handle)
        raise OSError(err, "SetInformationJobObject failed")

    _JOB_HANDLE = handle
    log.debug("created Job Object handle=%s", handle)
    return handle


def assign_process(job_handle: object, pid: int) -> None:
    """Add PID to the job. Called once per spawned sidecar."""
    if sys.platform != "win32":
        return
    k32 = _kernel32()
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL

    proc_handle = k32.OpenProcess(
        PROCESS_TERMINATE | PROCESS_SET_QUOTA,
        False,
        pid,
    )
    if not proc_handle:
        log.warning("OpenProcess(pid=%s) failed; not assigned to job", pid)
        return

    try:
        ok = k32.AssignProcessToJobObject(job_handle, proc_handle)  # type: ignore[arg-type]
        if not ok:
            err = ctypes.get_last_error()
            log.warning("AssignProcessToJobObject(pid=%s) failed err=%s", pid, err)
        else:
            log.debug("assigned pid=%s to job", pid)
    finally:
        k32.CloseHandle(proc_handle)
