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
