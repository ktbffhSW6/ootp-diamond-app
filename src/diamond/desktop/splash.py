"""Splash HTML helper — single-window-morph pattern.

pywebview only supports one ``webview.start()`` call per process, so a
separate splash window in its own GUI loop is impossible. Instead, the
launcher opens **one** main window initialized with the splash HTML
and an already-correct (large) size; once sidecars are ready, a
background thread calls ``window.load_url(main_url)`` to swap the
content. ``load_url`` is thread-safe in pywebview.

This module is just a small loader for the asset HTML so the
launcher stays focused.
"""

from __future__ import annotations

from diamond.desktop import paths


def html() -> str:
    """Return the splash HTML, with a small inline fallback if the
    asset file is missing (frozen-bundle hiccup).
    """
    asset = paths.assets_dir() / "splash.html"
    if asset.exists():
        return asset.read_text(encoding="utf-8")
    return _FALLBACK_HTML


_FALLBACK_HTML = """\
<!doctype html>
<html><head><meta charset="utf-8"><title>Diamond</title>
<style>
html,body{margin:0;height:100%;background:#0b1220;color:#e8eef9;
font-family:-apple-system,Segoe UI,Roboto,sans-serif;
display:flex;align-items:center;justify-content:center;flex-direction:column}
.title{font-size:28px;font-weight:600;margin-bottom:8px}
.sub{font-size:13px;color:#94a8c4;margin-bottom:18px}
.ring{width:28px;height:28px;border-radius:50%;
border:2px solid rgba(148,168,196,.25);border-top-color:#5b8def;
animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<div class="title">Diamond</div>
<div class="sub">Starting services…</div>
<div class="ring"></div>
</body></html>
"""
