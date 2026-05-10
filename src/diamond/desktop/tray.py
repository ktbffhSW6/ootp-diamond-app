"""System tray icon — quit / show / open Metabase.

Runs in a daemon thread so the pywebview GUI loop can stay on the
main thread (Win32 / Cocoa requirement). pystray drives its own GTK /
Win32 / Cocoa loop internally; we just feed it a menu and an icon.

If anything fails (missing pystray, no Pillow, headless server...),
the launcher falls through and runs without a tray. Tray is
nice-to-have UX, never load-bearing.

Why a tray?

    - Quick "Quit Diamond" without finding the window.
    - "Show Diamond" focuses the window if minimized to taskbar.
    - "Open Metabase" deep-links the BI workshop in default browser.
    - Persistent presence lets users close the main window but keep
      the backend warm (future v2 — current behavior is "close →
      shutdown" so this is an optional power-user mode).
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from diamond.desktop import paths

log = logging.getLogger(__name__)


def _make_default_icon():
    """Generate a minimal 64x64 RGBA icon at runtime.

    Avoids shipping a binary placeholder before we have artwork. A
    real icon at ``assets/tray_icon.png`` overrides this.
    """
    from PIL import Image, ImageDraw  # noqa: WPS433

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Diamond shape
    points = [(size // 2, 8), (size - 8, size // 2), (size // 2, size - 8), (8, size // 2)]
    draw.polygon(points, fill=(91, 141, 239, 255), outline=(232, 238, 249, 255))
    return img


def _load_icon():
    icon_path = paths.assets_dir() / "tray_icon.png"
    if icon_path.exists():
        from PIL import Image

        return Image.open(icon_path)
    return _make_default_icon()


def start(
    *,
    main_url: str,
    api_url: str,
    on_quit: Callable[[], None],
    on_show: Callable[[], None] | None = None,
    metabase_url: str = "http://127.0.0.1:3001",
) -> Callable[[], None]:
    """Start the tray icon thread. Returns a stop function.

    Args:
        main_url: URL the native window is hosting (for browser
            fallback if on_show isn't wired).
        api_url: FastAPI base — used by the "API docs" menu item.
        on_quit: called on tray Quit. Must be thread-safe (we're in
            pystray's thread, not Qt's).
        on_show: called on tray "Show Diamond". Should focus the
            native Qt window (un-minimize, raise, activate). The
            launcher wires this through a Qt Signal so the actual
            widget calls happen on the GUI thread; from pystray's
            side it's just `lambda: signal.emit()`. If None,
            falls back to opening main_url in the system browser
            (the pre-D34 behavior, kept as a safety net).
        metabase_url: deep-link target for "Open Metabase Workshop".

    The stop function is idempotent and safe to call multiple times.
    """
    import pystray  # noqa: WPS433

    icon_image = _load_icon()

    def _show_main(_icon, _item) -> None:
        # The native Qt window is already up; tray "Show" focuses
        # it (raises + activates) rather than spawning a duplicate
        # in the browser. on_show is provided by the launcher and
        # marshals to the GUI thread via a Qt signal.
        if on_show is not None:
            try:
                on_show()
                return
            except Exception:
                log.exception("on_show raised; falling back to browser")
        # Fallback: deep-link via default browser. Only fires if
        # on_show wasn't wired or raised.
        webbrowser.open(main_url)

    def _open_metabase(_icon, _item) -> None:
        webbrowser.open(metabase_url)

    def _open_api_docs(_icon, _item) -> None:
        webbrowser.open(f"{api_url}/docs")

    def _quit(icon, _item) -> None:
        try:
            on_quit()
        finally:
            try:
                icon.stop()
            except Exception:
                pass

    menu = pystray.Menu(
        pystray.MenuItem("Show Diamond", _show_main, default=True),
        pystray.MenuItem("Open Metabase Workshop", _open_metabase),
        pystray.MenuItem("API docs (Swagger)", _open_api_docs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Diamond", _quit),
    )

    icon = pystray.Icon(
        name="diamond",
        icon=icon_image,
        title="Diamond",
        menu=menu,
    )

    def _run() -> None:
        try:
            icon.run()
        except Exception:
            log.exception("tray thread crashed")

    t = threading.Thread(target=_run, name="diamond-tray", daemon=True)
    t.start()

    def stop() -> None:
        try:
            icon.stop()
        except Exception:
            log.debug("tray icon.stop() raised", exc_info=True)

    return stop
