"""Run the app as a desktop window.

``python -m safety_eval.desktop`` starts the Streamlit server hidden on a
free local port and puts the app in a window of its own, so the engineer
sees an application, not a terminal plus a browser tab. The window is tried
in order of how native it feels:

1. **pywebview** (the optional ``desktop`` extra): a real OS window (Edge
   WebView2 on Windows, WKWebView on Mac) titled like the app.
2. **A Chromium app window**: Edge or Chrome with ``--app=<url>``, which is
   a standalone window with no address bar or tabs. A private profile
   directory keeps the process attached so closing the window is seen.
3. **The default browser**, as a last resort.

Whichever way the window was opened, the server is shut down when it
closes. There is no console: launchers run this module with ``pythonw`` on
Windows and detached on Mac, so problems go to a log file
(``safety_eval_desktop.log`` in the system temp directory) instead of a
window nobody can see.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

log = logging.getLogger("safety_eval.desktop")

WINDOW_TITLE = "NCDOT Safety Studies"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launcher_path(tmp: str) -> str:
    """A script for ``streamlit run``: the repo's own launcher when the
    working directory is a checkout, else one written to ``tmp`` (a wheel
    install has no streamlit_app.py on disk)."""
    repo = os.path.join(os.getcwd(), "streamlit_app.py")
    if os.path.exists(repo):
        return repo
    path = os.path.join(tmp, "safety_eval_launcher.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("from safety_eval.app import main\nmain()\n")
    return path


def start_server(port: int, tmp: str) -> subprocess.Popen:
    """The Streamlit server as a hidden child process."""
    cmd = [sys.executable, "-m", "streamlit", "run", _launcher_path(tmp),
           "--server.port", str(port), "--server.headless", "true",
           "--browser.gatherUsageStats", "false"]
    kwargs: dict = {"stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL}
    if os.name == "nt":                       # no console window flashes up
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


def wait_up(url: str, timeout: float = 90.0, server=None) -> bool:
    """True once ``url`` answers; False on timeout or a dead server."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if server is not None and server.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.4)
    return False


# --------------------------------------------------------------------------- #
# the window, most native first
# --------------------------------------------------------------------------- #
_SPLASH = """<!doctype html><html><head><title>{title}</title></head>
<body style="margin:0;font-family:'Segoe UI',sans-serif;background:#F4F6F9;
display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center;color:#171B26">
<h1 style="font-weight:600;margin-bottom:.3em">{title}</h1>
<p style="color:#5B6472">Starting the analysis engine&hellip;</p>
</div></body></html>"""

_FAILED = """<!doctype html><html><body style="margin:0;font-family:
'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;
height:100vh"><div style="text-align:center;color:#171B26">
<h2>The app did not start</h2>
<p>Close this window, run the installer again, and if it still fails send
along the log file named safety_eval_desktop.log from the temp folder.</p>
</div></body></html>"""


def _open_pywebview(url: str, server: subprocess.Popen) -> bool:
    """A native window via pywebview; blocks until it is closed.

    The window opens at once on a splash, then loads the app when the
    server answers, so a double click always shows something within a
    second or two.
    """
    try:
        import webview
    except Exception as exc:                  # noqa: BLE001 - fall through
        log.info("pywebview not available (%s)", exc)
        return False
    try:
        window = webview.create_window(
            WINDOW_TITLE, html=_SPLASH.format(title=WINDOW_TITLE),
            width=1500, height=950)

        def _load():
            if wait_up(url, server=server):
                window.load_url(url)
            else:
                log.error("server never answered; window shows the notice")
                window.load_html(_FAILED)

        webview.start(_load)
        return True
    except Exception as exc:                  # noqa: BLE001 - fall through
        log.warning("pywebview window failed: %s", exc)
        return False


def _browser_candidates() -> list[str]:
    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", ""),
                 os.environ.get("LocalAppData", "")]
        rel = [r"Microsoft\Edge\Application\msedge.exe",
               r"Google\Chrome\Application\chrome.exe"]
        return [os.path.join(root, r) for r in rel for root in roots if root]
    if sys.platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    return ["/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome"]


def _open_app_window(url: str, tmp: str) -> bool:
    """An Edge or Chrome app-mode window; blocks until it is closed."""
    for exe in _browser_candidates():
        if not os.path.exists(exe):
            continue
        profile = os.path.join(tmp, "appwindow-profile")
        try:
            proc = subprocess.Popen(
                [exe, f"--app={url}", f"--user-data-dir={profile}",
                 "--no-first-run", "--no-default-browser-check",
                 "--window-size=1500,950"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.warning("%s failed to start: %s", exe, exc)
            continue
        log.info("app window via %s", exe)
        proc.wait()
        return True
    return False


def _open_default_browser(url: str, server: subprocess.Popen) -> None:
    """Last resort: the default browser; the server runs until it exits."""
    import webbrowser
    webbrowser.open(url)
    log.info("default browser opened; serving until the server exits")
    try:
        server.wait()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="safety-eval-desktop",
        description="Run the app in a desktop window.")
    parser.add_argument("--probe", action="store_true",
                        help="start the server, confirm it answers, shut "
                             "it down and exit (used by tests and doctor)")
    parser.add_argument("--browser", action="store_true",
                        help="skip the app window and use the default "
                             "browser")
    args = parser.parse_args(argv)

    logging.basicConfig(
        filename=os.path.join(tempfile.gettempdir(),
                              "safety_eval_desktop.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="safety-eval-desktop-") as tmp:
        server = start_server(port, tmp)
        try:
            # The pywebview window opens on a splash at once and waits for
            # the server itself; every other path waits here first.
            if not (args.probe or args.browser) \
                    and _open_pywebview(url, server):
                return 0
            if not wait_up(url, server=server):
                log.error("the app server never came up on %s", url)
                print(f"The app server did not start; see the log in "
                      f"{tempfile.gettempdir()}", file=sys.stderr)
                return 1
            if args.probe:
                print(f"ok: served {url}")
                return 0
            log.info("serving %s", url)
            if args.browser:
                _open_default_browser(url, server)
            elif not _open_app_window(url, tmp):
                _open_default_browser(url, server)
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
        log.info("window closed; server stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
