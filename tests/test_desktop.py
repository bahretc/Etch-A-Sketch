"""The desktop launcher: hidden server up, window fallbacks, clean stop."""
import os
import subprocess
import sys

import pytest

from safety_eval import desktop


class _DeadServer:
    def poll(self):
        return 1


def test_wait_up_gives_up_at_once_on_a_dead_server():
    port = desktop._free_port()
    assert desktop.wait_up(f"http://127.0.0.1:{port}", timeout=5.0,
                           server=_DeadServer()) is False


def test_the_launcher_file_is_written_when_there_is_no_checkout(tmp_path,
                                                                monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = desktop._launcher_path(str(tmp_path))
    assert path.endswith("safety_eval_launcher.py")
    text = open(path, encoding="utf-8").read()
    assert "from safety_eval.app import main" in text


def test_the_repo_launcher_wins_when_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "streamlit_app.py").write_text("x = 1\n")
    assert desktop._launcher_path(str(tmp_path)).endswith("streamlit_app.py")


def test_windows_candidates_cover_edge_and_chrome(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.setenv("LocalAppData", r"C:\Users\x\AppData\Local")
    paths = desktop._browser_candidates()
    assert any("msedge.exe" in p for p in paths)
    assert any("chrome.exe" in p for p in paths)


@pytest.mark.skipif(not os.environ.get("SAFETY_EVAL_DESKTOP_PROBE", "1"),
                    reason="probe disabled")
def test_the_probe_serves_and_stops():
    """End to end: the hidden server comes up on a free port, answers,
    and is shut down; nothing is left listening."""
    pytest.importorskip("streamlit")
    out = subprocess.run(
        [sys.executable, "-m", "safety_eval.desktop", "--probe"],
        capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok: served http://127.0.0.1:")


# --------------------------------------------------------------------------- #
# what the window remembers, and where it opens
# --------------------------------------------------------------------------- #
def test_a_first_run_on_a_small_laptop_opens_maximized_and_on_screen():
    from safety_eval.desktop import MIN_SIZE, initial_geometry
    g = initial_geometry({}, (1366, 768))
    assert g["maximized"] is True
    assert g["width"] <= 1366 and g["height"] <= 768
    assert (g["width"], g["height"]) >= MIN_SIZE
    assert (g["x"], g["y"]) == (None, None)
    big = initial_geometry({}, (1920, 1080))
    assert (big["width"], big["height"], big["maximized"]) == (1500, 950, False)


def test_the_remembered_size_and_place_come_back_when_they_still_fit():
    from safety_eval.desktop import initial_geometry
    g = initial_geometry({"width": 1200, "height": 800, "x": 40, "y": 30},
                         (1920, 1080))
    assert (g["width"], g["height"], g["x"], g["y"]) == (1200, 800, 40, 30)
    # a place on a monitor that is gone is dropped; the OS places it
    off = initial_geometry({"width": 1200, "height": 800, "x": 3000,
                            "y": 30}, (1920, 1080))
    assert (off["x"], off["y"]) == (None, None)
    # never below the minimum the pages are laid out for
    tiny = initial_geometry({"width": 400, "height": 300}, None)
    assert (tiny["width"], tiny["height"]) == (1024, 700)
    assert initial_geometry({"maximized": True}, None)["maximized"] is True
    # garbage in the file reads as a first run, not a crash
    junk = initial_geometry({"width": "wide", "height": True}, (1920, 1080))
    assert (junk["width"], junk["height"]) == (1500, 950)


def test_window_state_round_trips_and_a_bad_file_reads_as_empty(tmp_path):
    from safety_eval.desktop import load_window_state, save_window_state
    path = tmp_path / "sub" / "window.json"
    assert load_window_state(str(path)) == {}
    save_window_state({"width": 1300, "height": 900, "maximized": False},
                      str(path))
    assert load_window_state(str(path))["width"] == 1300
    path.write_text("{not json")
    assert load_window_state(str(path)) == {}


def test_the_splash_follows_the_system_theme_and_formats_cleanly():
    from safety_eval.desktop import _FAILED, _SPLASH, WINDOW_TITLE
    html = _SPLASH.format(title=WINDOW_TITLE)
    assert "prefers-color-scheme: dark" in html
    assert "prefers-reduced-motion" in html
    assert html.count(WINDOW_TITLE) == 2
    assert "prefers-color-scheme: dark" in _FAILED
