"""TEAAS import writers, pinned byte for byte against real NCDOT files.

examples/04-15-39049 holds the Before_Import.txt and After_Import.txt actually
fed to TEAAS for that evaluation, so the format is not inferred here: the
writer reproduces those files exactly or the test fails.
"""
import os
from datetime import date

import pytest

from safety_eval.models import Crash
from safety_eval.teaas import (crashes_from_workbook, import_rows,
                               parse_import_list, write_feature_list,
                               write_import_list, write_period_imports)

ARCHIVE = "examples/04-15-39049"
WB = f"{ARCHIVE}/Section Evaluation Workbook - 04-15-39049.xlsx"


# ---------------------------------------------------------------------------
# the format itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Before_Import.txt", "After_Import.txt"])
@pytest.mark.skipif(not os.path.exists(ARCHIVE), reason="archive example absent")
def test_round_trips_a_real_import_file_byte_for_byte(name, tmp_path):
    real = open(f"{ARCHIVE}/{name}", "rb").read()
    rows = []
    for line in real.decode().split("\r\n"):
        if line.strip():
            crash_id, mp = line.split("|")
            rows.append((crash_id, float(mp.strip())))

    out = tmp_path / name
    assert write_import_list(str(out), rows) == len(rows)
    assert out.read_bytes() == real


@pytest.mark.skipif(not os.path.exists(ARCHIVE), reason="archive example absent")
def test_real_import_files_have_unique_crash_ids():
    """The dedupe guard below only holds if TEAAS files really are 1 row/crash."""
    for name in ("Before_Import.txt", "After_Import.txt"):
        text = open(f"{ARCHIVE}/{name}").read()
        ids = [ln.split("|")[0] for ln in text.splitlines() if ln.strip()]
        assert len(ids) == len(set(ids))


def test_format_is_pipe_tab_three_decimals_crlf(tmp_path):
    out = tmp_path / "i.txt"
    write_import_list(str(out), [("104509841", 17.691), ("104515269", 17.8)])
    assert out.read_bytes() == b"104509841|\t17.691\r\n104515269|\t17.800\r\n"


def test_written_file_reads_back_through_our_own_parser(tmp_path):
    out = tmp_path / "i.txt"
    write_import_list(str(out), [("1", 1.5), ("2", 2.25)])
    assert parse_import_list(out.read_text()) == {"1": 1.5, "2": 2.25}


def test_empty_row_set_writes_an_empty_file(tmp_path):
    out = tmp_path / "i.txt"
    assert write_import_list(str(out), []) == 0
    assert out.read_bytes() == b""


def test_blank_crash_ids_are_skipped(tmp_path):
    out = tmp_path / "i.txt"
    assert write_import_list(str(out), [("", 1.0), ("  ", 2.0), ("7", 3.0)]) == 1


def test_creates_the_output_directory(tmp_path):
    out = tmp_path / "nested" / "deeper" / "i.txt"
    write_import_list(str(out), [("1", 1.0)])
    assert out.exists()


# ---------------------------------------------------------------------------
# the duplicate guard
# ---------------------------------------------------------------------------

def test_a_crash_with_two_different_mileposts_is_refused(tmp_path):
    """TEAAS would silently take one of them; the study must not depend on which."""
    with pytest.raises(ValueError, match="different mileposts"):
        write_import_list(str(tmp_path / "i.txt"),
                          [("104509841", 17.691), ("104509841", 2.310)])


def test_an_exact_duplicate_is_collapsed(tmp_path):
    out = tmp_path / "i.txt"
    assert write_import_list(str(out), [("1", 4.0), ("1", 4.0)]) == 1


# ---------------------------------------------------------------------------
# feature list (format NOT verified against a real file)
# ---------------------------------------------------------------------------

def test_feature_list_format(tmp_path):
    out = tmp_path / "f.txt"
    write_feature_list(str(out), [("SR 1716", 17.691)])
    assert out.read_bytes() == b"SR 1716|17.691\r\n"


def test_over_length_feature_text_raises_rather_than_truncating(tmp_path):
    with pytest.raises(ValueError, match="20"):
        write_feature_list(str(tmp_path / "f.txt"),
                           [("SR 1716 AT BUFFALO ROAD JUNCTION", 17.691)])


def test_feature_text_truncates_only_when_asked(tmp_path):
    out = tmp_path / "f.txt"
    write_feature_list(str(out), [("SR 1716 AT BUFFALO ROAD", 17.691)],
                       truncate=True)
    assert out.read_bytes() == b"SR 1716 AT BUFFALO R|17.691\r\n"


# ---------------------------------------------------------------------------
# building the rows from classified crashes
# ---------------------------------------------------------------------------

def _crash(cid, mp, period="before", in_study=True, when=None):
    return Crash(crash_id=cid, mp=mp, period=period, in_study=in_study,
                 date=when)


def test_only_in_study_crashes_for_the_named_period():
    crashes = [_crash("1", 17.7), _crash("2", 17.7, period="after"),
               _crash("3", 17.7, in_study=False),
               _crash("4", 17.7, in_study=None)]
    rows, held = import_rows(crashes, "before")
    assert rows == [("1", 17.7)] and held == []


def test_a_recorded_new_mp_wins_over_the_coded_milepost():
    """The RE case (docs/03): the reviewer's correction is what gets imported."""
    rows, _ = import_rows([_crash("1", 2.310)], "before", {"1": 17.691})
    assert rows == [("1", 17.691)]


def test_a_crash_with_no_milepost_is_held_not_dropped():
    rows, held = import_rows([_crash("1", None), _crash("2", 17.7)], "before")
    assert rows == [("2", 17.7)]
    assert [h[0] for h in held] == ["1"]


def test_rows_come_out_in_crash_date_order():
    """Both real import files are date-ordered; the sheets they came from are not."""
    crashes = [_crash("300", 17.7, when=date(2018, 5, 1)),
               _crash("100", 17.8, when=date(2016, 1, 9)),
               _crash("200", 17.9, when=date(2017, 3, 4))]
    rows, _ = import_rows(crashes, "before")
    assert [r[0] for r in rows] == ["100", "200", "300"]


def test_without_dates_input_order_is_preserved():
    crashes = [_crash("300", 17.7), _crash("100", 17.8)]
    rows, _ = import_rows(crashes, "before")
    assert [r[0] for r in rows] == ["300", "100"]


def test_write_period_imports_splits_by_period(tmp_path):
    crashes = [_crash("1", 17.691), _crash("2", 17.811),
               _crash("3", 17.7, period="after")]
    out = write_period_imports(str(tmp_path), crashes)
    assert out["before"][1] == 2 and out["after"][1] == 1
    assert "held" not in out
    assert open(out["after"][0], "rb").read() == b"3|\t17.700\r\n"


def test_write_period_imports_writes_a_held_file_that_is_not_importable(tmp_path):
    out = write_period_imports(str(tmp_path), [_crash("1", None)])
    path, n = out["held"]
    assert n == 1
    text = open(path).read()
    assert text.startswith("# Not a TEAAS import file.")
    assert parse_import_list(text) == {}          # cannot be fed to TEAAS


# ---------------------------------------------------------------------------
# end to end against the archive
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (os.path.exists(WB) and os.path.exists(ARCHIVE)),
                    reason="archive example absent")
def test_rebuilds_the_archive_imports_from_the_workbook(tmp_path):
    """Workbook in, the real Before_Import.txt and After_Import.txt out."""
    pytest.importorskip("openpyxl")
    crashes = crashes_from_workbook(WB)
    assert len(crashes) == 59

    out = write_period_imports(str(tmp_path), crashes)
    assert "held" not in out
    for period, name in (("before", "Before_Import.txt"),
                         ("after", "After_Import.txt")):
        assert (open(out[period][0], "rb").read()
                == open(f"{ARCHIVE}/{name}", "rb").read()), name
