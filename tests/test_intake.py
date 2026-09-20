"""The drop-zone sniffer: files are recognised from what they are."""
import io

import openpyxl
import pytest

from safety_eval import intake, workspace as wsm

FICHE = (b'"North Carolina Department of Transportation\n'
         b'Traffic Engineering Accident Analysis System\nFiche Report"\n'
         b'"Municipality","On Road","Miles"\n"ASHEVILLE","US 19","0.038"\n')
INITIAL = (b',"North Carolina Department of Transportation\n'
           b'Traffic Engineering Accident Analysis System\n'
           b'Intersection Analysis Report"\n')
IDS = b"CRASH ID|ON RD CD|SVRTY|DATE|TYPE|\n107632131|50023561|3|08/01/2021 14:46|14|\n"
DETAILED = (b'"Municipality","On Road","Miles","Crash ID","Date","Latitude",'
            b'"Longitude","Source"\n"ASHEVILLE","US 19","0.1","107837412",'
            b'"2024-08-09","35.5","-82.6",""\n')
PARAMS = b'"County","County Code","Division","Y-Line Feet"\n"BUNCOMBE","11","13","150.0"\n'
MP_IMPORT = b"106749939|\t0.000\r\n106890975|\t0.000\r\n"


@pytest.mark.parametrize("name,data,role", [
    ("41000079549_Fiche.csv", FICHE, "fiche_csv"),
    ("anything.csv", INITIAL, "initial_study_csv"),
    ("InitialID.txt", IDS, "initial_ids_txt"),
    ("DetailedFiche.csv", DETAILED, "detailed_fiche_csv"),
    ("scan.tif", b"II*\x00", "crash_report"),
    ("route.geojson", b"{}", "centerline"),
    ("memo.docx", b"PK", "analysis_memo"),
])
def test_teaas_exports_are_recognised_by_content(name, data, role):
    det = intake.sniff(name, data)
    assert det.role == role, det


def test_the_name_does_not_decide_a_csv():
    """A Fiche Report saved under an odd name is still the Fiche Report."""
    assert intake.sniff("export (3).csv", FICHE).role == "fiche_csv"
    assert intake.sniff("Fiche.csv", INITIAL).role == "initial_study_csv"


def test_a_milepost_import_asks_which_period():
    det = intake.sniff("import.txt", MP_IMPORT)
    assert det.role is None
    assert set(det.choices) == {"before_mp", "after_mp"}


def test_the_parameters_sheet_is_named_and_not_attached():
    det = intake.sniff("DetailedFiche_parameters.csv", PARAMS)
    assert det.role is None and "parameters" in det.label.lower()


def test_a_fiche_workbook_is_told_from_an_evaluation_workbook():
    wb = openpyxl.Workbook()
    wb.active.title = "41000079305_Fiche"
    buf = io.BytesIO(); wb.save(buf)
    assert intake.sniff("x.xlsx", buf.getvalue()).role == "workbook"
    assert intake.sniff("x_reviewed.xlsx", buf.getvalue()).role == "reviewed_workbook"
    wb = openpyxl.Workbook()
    wb.active.title = "Filtered Fiche"
    buf = io.BytesIO(); wb.save(buf)
    assert intake.sniff("eval.xlsx", buf.getvalue()).role == "evaluation_workbook"


def test_attach_all_files_the_sure_ones_and_returns_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path))
    ws = wsm.Workspace.create("41000079549", study_type="hsip")
    done, skipped = intake.attach_all(ws, [
        ("41000079549_Fiche.csv", FICHE), ("InitialID.txt", IDS),
        ("import.txt", MP_IMPORT), ("params.csv", PARAMS)])
    assert {d.role for d in done} == {"fiche_csv", "initial_ids_txt"}
    assert [n for n, _ in skipped] == ["import.txt", "params.csv"]
    assert ws.path("fiche_csv").endswith("41000079549_Fiche.csv")
    # the engineer's pick wins over the sniff, and "skip" skips
    done, skipped = intake.attach_all(
        ws, [("import.txt", MP_IMPORT), ("InitialID.txt", IDS)],
        roles={"import.txt": "before_mp", "InitialID.txt": "skip"})
    assert [d.role for d in done] == ["before_mp"]
    assert [n for n, _ in skipped] == ["InitialID.txt"]
