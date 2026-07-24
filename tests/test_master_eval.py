"""Master Evaluation Spreadsheet reader tests (synthetic sheet in the real
layout: banner row 1, header row 2, data from row 3). Field mapping was
validated against the real 030724 spreadsheet: the drafted document for
41000069597 matches the archived draft on every DB-sourced field."""
import pytest

from safety_eval.master_eval import find_assignment, to_assumptions_data


@pytest.fixture()
def master(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SS-HE Projects - test"
    ws.append(["", "EVALUATION ASSIGNMENT TRACKING"])          # banner
    ws.append(["#", "Evaluation Order Number", "Evaluation Comments",
               "Category (Web)", "Division (Web)", "County (Web)",
               "Analysis Type (Web)", "Location Type (Web)",
               "Geometry (Web)", "TIP (From DB)", "File Number (From DB)",
               "GPS Coordinates", "DIVISION (From DB)", "COUNTY (From DB)",
               "DESCRIPTION Of LOCATION (From DB)",
               "Project Improvement Description (From DB)",
               "TOTAL COST ESTIMATE (From DB)", "COMPLETION (From DB)",
               "Signal ID", "Crash History (from DB)",
               "Total Correctable Crashes (from DB)"])
    from datetime import datetime
    ws.append([1, 41000069597, "ASSIGNMENT #13", "All Way Stop", 8, "Lee",
               "Intersection", "4-Leg", "2 Lane @ 2 Lane", "SS-4908BT",
               "08-17-49850", "35.509870, -79.303193", 8, "Lee",
               "NC 42 at SR 1107 (Plank Rd).", "Install an all way stop.",
               11000, datetime(2018, 1, 25), "N/A",
               "27 total crashes from 5/1/2010 to 4/30/2020", 9])
    ws.append([2, 41000075552, "", "Rumble Strips", 2, "Greene",
               "Section", "", "", "SS-6002M", "02-20-61721",
               "35.441163, -77.824727", 2, "Greene",
               "US 13 between the Wayne County Line and NC 58",
               "Install rumble strips — sinusoidal.", 116000,
               datetime(2021, 10, 16), "", "", ""])
    path = str(tmp_path / "master.xlsx")
    wb.save(path)
    return path


def test_find_assignment_by_order(master):
    row = find_assignment(master, "41000069597")
    assert row["tip"] == "SS-4908BT"
    assert row["county"] == "Lee"
    with pytest.raises(KeyError):
        find_assignment(master, "41999999999")


def test_to_assumptions_data_maps_fields(master):
    data = to_assumptions_data(find_assignment(master, "41000069597"))
    assert data.order_id == "41000069597"
    assert data.project_id == "08-17-49850 (TIP #SS-4908BT)"
    assert data.county == "Lee" and data.division == "8"
    assert data.study_type.startswith("Intersection Analysis")
    assert "4-Leg" in data.study_type
    assert data.location == "NC 42 at SR 1107 (Plank Rd)."
    assert data.countermeasure == "Install an all way stop."
    assert data.project_cost == "$11,000"
    assert data.project_completion == "1/25/2018"
    assert data.signal_id is None                     # N/A reads as none
    assert "27 total crashes" in data.project_dev_summary
    assert "9 correctable" in data.project_dev_summary
    # draft leaves the engineer's fields empty (tool prepares, PE decides)
    assert data.target_crashes == ""
    assert data.teaas_date is None


def test_generated_draft_passes_style_gate(master, tmp_path):
    pytest.importorskip("docx")
    from safety_eval.assumptions_email import generate_assumptions_email

    # the DB text carries an em dash; the draft must come out clean (docs/05)
    data = to_assumptions_data(find_assignment(master, "41000075552"))
    assert "—" not in data.countermeasure
    out = str(tmp_path / "draft.docx")
    generate_assumptions_email(data, out)             # style gate enforces
