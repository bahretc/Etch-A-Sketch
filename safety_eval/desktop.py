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

The native window opens at the size and place it had when it was last
closed (``window.json`` in the per-user settings folder), fitted to the
screen, never smaller than 1024 x 700; it follows the system's light or dark
setting, lets text be selected and copied, zooms with Ctrl and the mouse
wheel, and asks before closing because closing stops a run in progress.

Whichever way the window was opened, the server is shut down when it
closes. There is no console: launchers run this module with ``pythonw`` on
Windows and detached on Mac, so problems go to a log file
(``safety_eval_desktop.log`` in the system temp directory) instead of a
window nobody can see.
"""
from __future__ import annotations

import json
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

#: The smallest window the pages are laid out for: below it the three- and
#: four-column rows stack and the sidebar covers the page.
MIN_SIZE = (1024, 700)
DEFAULT_SIZE = (1500, 950)


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
_SPLASH = """<!doctype html><html><head><title>{title}</title>
<meta name="color-scheme" content="light dark"><style>
body {{margin:0;height:100vh;display:flex;align-items:center;
  justify-content:center;background:#F4F6F9;color:#171B26;
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
h1 {{font-size:1.75rem;font-weight:600;margin:0 0 .5em}}
p {{font-size:1rem;line-height:1.5;margin:0;color:#5B6472}}
.pulse {{animation:pulse 1.6s ease-in-out infinite}}
@keyframes pulse {{50% {{opacity:.45}}}}
@media (prefers-color-scheme: dark) {{
  body {{background:#14171F;color:#E8EAF0}} p {{color:#AEB4BF}}}}
@media (prefers-reduced-motion: reduce) {{.pulse {{animation:none}}}}
</style></head><body><div style="text-align:center">
<h1>{title}</h1>
<p class="pulse">Starting the analysis engine&hellip;</p>
<p>Usually under half a minute.</p>
</div></body></html>"""

_FAILED = """<!doctype html><html><head>
<meta name="color-scheme" content="light dark"><style>
body {margin:0;height:100vh;display:flex;align-items:center;
  justify-content:center;background:#F4F6F9;color:#171B26;
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1 {font-size:1.75rem;font-weight:600;margin:0 0 .5em}
p {font-size:1rem;line-height:1.5;margin:0 auto;max-width:60ch}
@media (prefers-color-scheme: dark) {body {background:#14171F;color:#E8EAF0}}
</style></head><body><div style="text-align:center">
<h1>The app did not start</h1>
<p>Close this window, run the installer again, and if it still fails send
along the log file named safety_eval_desktop.log from the temp folder.</p>
</div></body></html>"""


# --------------------------------------------------------------------------- #
# what the window remembers between runs
# --------------------------------------------------------------------------- #
def state_dir() -> str:
    """The per-user folder the window remembers itself in."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = (os.environ.get("XDG_CONFIG_HOME")
                or os.path.expanduser("~/.config"))
    return os.path.join(base, "safety_eval")


def load_window_state(path: str | None = None) -> dict:
    """The size, place and maximized flag of the last window, or {} on a
    first run or when the file cannot be read."""
    path = path or os.path.join(state_dir(), "window.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_window_state(state: dict, path: str | None = None) -> None:
    """Write the window state; a failure is logged, never raised."""
    path = path or os.path.join(state_dir(), "window.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError as exc:
        log.info("window state not saved (%s)", exc)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def initial_geometry(state: dict, screen: tuple | None) -> dict:
    """Where the window opens.

    The remembered size and place when they still fit the screen; otherwise
    the default size fitted to the screen, maximized on a first run when
    the screen is smaller than the default. Never below MIN_SIZE unless the
    screen itself is smaller. ``screen`` is ``(width, height)`` in logical
    pixels, or None when the platform could not say.
    """
    width, height = DEFAULT_SIZE
    x = y = None
    rw, rh = _int(state.get("width")), _int(state.get("height"))
    if rw and rh:
        width, height = max(rw, MIN_SIZE[0]), max(rh, MIN_SIZE[1])
        x, y = _int(state.get("x")), _int(state.get("y"))
    maximized = bool(state.get("maximized"))
    if screen:
        sw, sh = screen
        width = max(min(width, sw - 60), min(MIN_SIZE[0], sw))
        height = max(min(height, sh - 80), min(MIN_SIZE[1], sh))
        if x is not None and y is not None and not (
                0 <= x <= sw - 100 and 0 <= y <= sh - 100):
            x = y = None              # remembered on a screen no longer there
        if not state and (sw < DEFAULT_SIZE[0] + 60
                          or sh < DEFAULT_SIZE[1] + 80):
            maximized = True
    if x is None or y is None:
        x = y = None
    return {"width": width, "height": height, "x": x, "y": y,
            "maximized": maximized}


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
        state = load_window_state()
        screen = None
        try:
            first = webview.screens[0]     # logical pixels, like width/height
            screen = (int(first.width), int(first.height))
        except Exception as exc:              # noqa: BLE001 - keep defaults
            log.info("screen size unknown (%s); default window", exc)
        geo = initial_geometry(state, screen)
        window = webview.create_window(
            WINDOW_TITLE, html=_SPLASH.format(title=WINDOW_TITLE),
            width=geo["width"], height=geo["height"], x=geo["x"],
            y=geo["y"], min_size=MIN_SIZE, maximized=geo["maximized"],
            # As in a browser: text can be selected and copied with Ctrl+C,
            # and Ctrl with the mouse wheel zooms.
            text_select=True, zoomable=True,
            # Closing stops a run in progress, so the OS asks first, in its
            # own dialog with its own button order.
            confirm_close=True)

        def _resized(width, height):
            if not state.get("maximized"):
                state.update(width=int(width), height=int(height))

        def _moved(x, y):
            if not state.get("maximized"):
                state.update(x=int(x), y=int(y))

        def _maximized():
            state["maximized"] = True

        def _restored():
            state["maximized"] = False

        def _closing():
            save_window_state(state)

        for name, fn in (("resized", _resized), ("moved", _moved),
                         ("maximized", _maximized), ("restored", _restored),
                         ("closing", _closing)):
            try:
                event = getattr(window.events, name)
                event += fn
            except Exception as exc:          # noqa: BLE001 - a nicety only
                log.info("window event %s unavailable (%s)", name, exc)

        def _load():
            if wait_up(url, server=server):
                window.load_url(url)
            else:
                log.error("server never answered; window shows the notice")
                window.load_html(_FAILED)

        storage = os.path.join(state_dir(), "webview")
        try:
            os.makedirs(storage, exist_ok=True)
        except OSError:
            storage = None
        # private_mode=False with a storage folder: the page's own settings
        # (the theme the engineer picked, the sidebar) survive a restart.
        webview.start(_load, private_mode=storage is None,
                      storage_path=storage,
                      localization={"global.quitConfirmation":
                                    f"Close {WINDOW_TITLE}? A run in "
                                    "progress stops."})
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
                 # the profile is temporary, so there is no saved size to
                 # restore; a maximized window fits any screen
                 "--start-maximized"],
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
