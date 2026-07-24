"""Supervision-pair extractor tests. Drawing extraction is validated in
session against the real SS-6002M workbook (aerial insert at H42 with the
'S-1 START Wayne Co. Line (MP 0.00)' callout, LEGEND text box at K52);
these tests cover the same paths on a synthetic workbook plus the
provenance rule."""
import pytest

from safety_eval.report_dataset import (extract_record, results_sheet_names,
                                        results_text, used_results_sheet,
                                        write_dataset)


@pytest.fixture()
def workbook(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ff = wb.active
    ff.title = "Filtered Fiche"
    ff.append(["Muni.\nCode", "On Road", "Miles", "Dir\nFrom", "From Road",
               "Toward Road", "Milepost Road", "MP", "IS?", "New MP", "MA",
               "Crash ID", "Date", "T", "C", "F", "L", "S", "Comments"])
    ff.append([0, "US 13", 0, "", "A", "B", "US 13", 1.0, "IS", 1.0, "",
               "105044801", "2017-01-01", 19, 1, 0, 1, "C", ""])
    r1 = wb.create_sheet("1 page results - 1 Target")
    r1["C10"] = ("Items for Discussion: the 2 lane departure crashes in the "
                 "before period were both wet-road run-off-road events on "
                 "the southern curve near the county line.")
    r1["C12"] = "n/a"
    r2 = wb.create_sheet("1 page results - 2 Targets")
    r2["P8"] = "Cells shaded TAN need to be filled in prior to printing"
    path = str(tmp_path / "eval.xlsx")
    wb.save(path)
    return path


def test_results_sheet_names_covers_archive_variants():
    """Real archive workbooks deliver results on renamed one-pagers
    (41000075105, 41000064924, 41000075594); anything ending in
    '- N Target(s)' is a results sheet, lookalikes are not."""
    names = ["Step-by-Step Instructions", "Typical Target Crash Types",
             "Typical Target Crashes", "Filtered Fiche",
             "1 page results - 1 Target", "1 page results - 2 Targets",
             "Results - 1 Target", "Results - 2 Targets",
             "Unequal time periods - 1 Target",
             "Precip. Data Evals - 1 Target", "3+ Target Crashes"]
    picked = results_sheet_names(names)
    assert picked == ["1 page results - 1 Target",
                      "1 page results - 2 Targets", "Results - 1 Target",
                      "Results - 2 Targets", "Unequal time periods - 1 Target",
                      "Precip. Data Evals - 1 Target", "3+ Target Crashes"]


def test_variant_results_sheet_extracted(workbook, tmp_path):
    """A workbook whose only prose lives on a variant one-pager must not
    extract empty targets (the 41000075105 case)."""
    import openpyxl

    wb = openpyxl.load_workbook(workbook)
    wb["1 page results - 1 Target"].title = "Results - 1 Target"
    path = str(tmp_path / "variant.xlsx")
    wb.save(path)
    rec = extract_record(path, {"wo": "X", "split": "train"})
    assert "Results - 1 Target" in rec["targets"]["results_text"]
    assert used_results_sheet(rec) == "Results - 1 Target"


def test_results_text_and_used_sheet(workbook):
    text = results_text(workbook)
    assert "1 page results - 1 Target" in text
    assert any("Items for Discussion" in t
               for t in text["1 page results - 1 Target"].values())
    rec = extract_record(workbook, {"wo": "X", "split": "train"})
    assert used_results_sheet(rec) == "1 page results - 1 Target"


def test_extract_record_shape_and_dataset(workbook, tmp_path):
    rec = extract_record(workbook, {"wo": "41000000001", "split": "verify",
                                    "analysis_type": "section",
                                    "countermeasure_family": "rumble-strips",
                                    "assumptions_source": "msg"},
                         assumptions={"target_crashes": "Lane Departure"})
    assert rec["wo"] == "41000000001"
    assert rec["inputs"]["assumptions"]["target_crashes"] == "Lane Departure"
    assert rec["inputs"]["tallies"]["statuses"] == {"IS": 1}
    assert rec["targets"]["results_text"]
    out = str(tmp_path / "data.jsonl")
    assert write_dataset([rec], out) == 1
    import json
    with open(out) as fh:
        assert json.loads(fh.readline())["split"] == "verify"


def test_draft_assumptions_are_refused(workbook):
    """The provenance rule (docs/10): draft-sourced assumptions never feed
    the model."""
    with pytest.raises(ValueError):
        extract_record(workbook,
                       {"wo": "X", "assumptions_source": "docx-draft"},
                       assumptions={"target_crashes": "..."})
    # but classification-only meta with no assumptions attached is fine
    rec = extract_record(workbook,
                         {"wo": "X", "assumptions_source": "docx-draft"})
    assert rec["inputs"]["assumptions"] is None
