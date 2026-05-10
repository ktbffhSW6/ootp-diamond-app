"""Desktop shell (D32) — native pywebview window over FastAPI + Next.js.

Diamond ships as a single ``Diamond.exe`` that:

1. Acquires a Windows named-mutex single-instance lock (re-launching
   focuses the existing window instead of spawning a duplicate).
2. Wraps both child processes in a Windows Job Object configured with
   ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` so a hard-killed launcher
   takes its kids down — no zombie uvicorn / node ever.
3. Starts uvicorn in a daemon thread (in-process) bound to 127.0.0.1.
4. Spawns the Next.js standalone server as a hidden child (no console
   window) bound to 127.0.0.1.
5. Probes both ports until ready, then opens a pywebview window
   pointed at the Next.js URL. A splash window covers the cold-start
   gap so the user never sees a blank pre-render.
6. On window close: terminates Next.js, signals uvicorn, exits.

The dev workflow (``dev.bat``) is unaffected — that path is for
hot-reload coding. The desktop shell is the production user surface.

See ``docs/DESKTOP.md`` for install / build / troubleshooting.
"""
