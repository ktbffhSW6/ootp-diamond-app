"""Single-instance enforcement via Windows named mutex.

A double-click on Diamond.exe while it's already running should:

    1. NOT spawn a second copy.
    2. Bring the existing window to the foreground.

We use ``CreateMutexW`` with a stable name. The first launcher gets
ownership; subsequent launchers see ``ERROR_ALREADY_EXISTS`` and exit
after asking Windows to focus the existing main window by title.

The mutex name is process-namespaced (``Local\\``) so it doesn't
collide with other users on the same machine.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Optional

log = logging.getLogger(__name__)

# Stable across versions; bump only if a future major rev needs to
# coexist with an older one (we don't anticipate that).
MUTEX_NAME = "Local\\Diamond.OOTP.Desktop.SingleInstance"
WINDOW_TITLE = "Diamond — Building the Green Monster"

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

_HELD_HANDLE: Optional[int] = None


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def acquire() -> Optional[int]:
    """Return the held mutex handle, or None if another instance owns it."""
    if sys.platform != "win32":
        return 0  # Non-windows: pretend we got it.

    global _HELD_HANDLE
    if _HELD_HANDLE is not None:
        return _HELD_HANDLE

    k32 = _kernel32()
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE

    handle = k32.CreateMutexW(None, True, MUTEX_NAME)
    err = ctypes.get_last_error()
    if not handle:
        log.warning("CreateMutexW failed err=%s — proceeding without lock", err)
        return 0
    if err == ERROR_ALREADY_EXISTS:
        # We got a handle but didn't get ownership. Close it and bail.
        k32.CloseHandle(handle)
        return None

    _HELD_HANDLE = handle
    return handle


def try_focus_existing() -> bool:
    """Best-effort: bring the existing window to the foreground."""
    if sys.platform != "win32":
        return False
    u32 = _user32()
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u32.FindWindowW.restype = wintypes.HWND
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.ShowWindow.restype = wintypes.BOOL
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.SetForegroundWindow.restype = wintypes.BOOL

    hwnd = u32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, SW_RESTORE)
    u32.SetForegroundWindow(hwnd)
    return True
