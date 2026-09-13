"""Filtered Fiche generation tests against the 04-15-39049 working set."""
import os

import pytest

from safety_eval.config import Config
from safety_eval.fiche_parser import parse_fiche
from safety_eval.filtered_sheet import populate_filtered_sheet, prescreen
from safety_eval.teaas import parse_crash_id_list, parse_import_list
from safety_eval.xlsx_patch import verify_integrity

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples", "04-15-39049")
TEMPLATE = os.path.join(
    HERE, "..", "templates", "Section Evaluation Workbook - 2023-12-04.xlsx")

needs_fixtures = pytest.mark.skipif(
    not os.path.exists(TEMPLATE), reason="fixtures not present")


@pytest.fixture(scope="module")
def ws():
    cfg = Config.load()
    fiche = parse_fiche(os.path.join(EX, "OriginalFiche.csv"))
    before = {c.crash_id for c in
              parse_crash_id_list(os.path.join(EX, "Before_ID.txt"), cfg)}
    after = {c.crash_id for c in
             parse_crash_id_list(os.path.join(EX, "After_ID.txt"), cfg)}
    mps = dict(parse_import_list(os.path.join(EX, "Before_Import.txt")))
    mps.update(parse_import_list(os.path.join(EX, "After_Import.txt")))
    return fiche, before, after, mps


@needs_fixtures
def test_prescreen_groups_and_statuses(ws):
    fiche, before, after, mps = ws
    groups = prescreen(fiche, before, after, mps,
                       study_routes={"SR 1003"}, mp_range=(17.691, 17.811))
    assert len(groups["in_study"]) == 59        # 42 + 17 determined crashes
    total = sum(len(v) for v in groups.values())
    assert total == len(fiche)                  # every crash exactly once
    # statuses only prefilled for determined crashes; RE iff milepost corrected
    for crash, status, new_mp in groups["in_study"]:
        assert status in ("IS", "RE")
        if status == "RE":
            assert new_mp is not None and (
                crash.mp is None or abs(crash.mp - new_mp) > 1e-9
                or abs(crash.mp - 999.999) < 1e-6)
    assert any(s == "RE" for _, s, _ in groups["in_study"])
    for _, status, _ in groups["review"] + groups["rest"]:
        assert status is None                   # engineer's call, never ours


@needs_fixtures
def test_intersection_type_never_emits_re(ws):
    fiche, before, after, mps = ws
    groups = prescreen(fiche, before, after, mps,
                       study_routes={"SR 1003"}, mp_range=(17.691, 17.811),
                       analysis_type="intersection")
    assert all(s == "IS" for _, s, _ in groups["in_study"])


@needs_fixtures
def test_populate_filtered_sheet(tmp_path, ws):
    import openpyxl

    fiche, before, after, mps = ws
    out = str(tmp_path / "filtered.xlsx")
    counts = populate_filtered_sheet(
        TEMPLATE, out, fiche, before, after, mps,
        study_routes={"SR 1003"}, mp_range=(17.691, 17.811))
    assert counts["in_study"] == 59
    assert verify_integrity(TEMPLATE, out).ok

    sheet = openpyxl.load_workbook(out)["Filtered Fiche"]
    assert sheet["L1"].value == "Crash ID"
    assert sheet["A2"].value == "IN STUDY"
    # first in-study row carries a prefilled status
    assert sheet["I3"].value in ("IS", "RE")
