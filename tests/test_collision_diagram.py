"""collision_diagram: CSV parsing and the fan-out strip drawing."""
import os

import pytest

pytest.importorskip("matplotlib")

from safety_eval.collision_diagram import (CrashSymbol, Feature, StripSpec, draw_strip_diagram, load_csv,  # noqa: E402
                                           parse_units)


def test_parse_units():
    assert parse_units("W:mv;N:st") == [("W", "mv"), ("N", "st")]
    assert parse_units("e") == [("E", "mv")]
    assert parse_units("") == []


def test_csv_and_drawing(tmp_path):
    csv = tmp_path / "c.csv"
    csv.write_text("crash_id,mp,units,type,severity,date,night,wet\n"
                   "107089722,1.450,W:mv,FO,B,09/23/22,1,0\n"
                   "107304540,1.469,W:mv;W:st,RE,O,04/14/23,0,0\n"
                   "107421047,1.750,S:mv,ANG,A,07/02/23,0,1\n")
    crashes = load_csv(str(csv))
    assert len(crashes) == 3 and crashes[0].night and crashes[2].wet and crashes[1].units[1] == ("W", "st")
    spec = StripSpec("Test", "sub", 1.31, 1.80, [Feature(1.45, "SR 1321")])
    out = draw_strip_diagram(crashes, spec, str(tmp_path / "d"))
    assert os.path.getsize(out["pdf"]) > 1000 and os.path.getsize(out["png"]) > 1000
    assert out["crashes"] == 3 and out["by_severity"] == {"A": 1, "B": 1, "O": 1}


def test_empty_list_still_draws(tmp_path):
    out = draw_strip_diagram([], StripSpec("Empty", mp_start=0.0, mp_end=2.0), str(tmp_path / "e"))
    assert out["crashes"] == 0 and os.path.exists(out["png"])
    assert CrashSymbol("1", 0.5).severity == "O"
