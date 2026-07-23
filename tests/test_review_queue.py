"""Review-queue tests: sheet read-back, docs/03 validation rules, queue
ordering, the audit trail, and template-preserving write-back, exercised on a
Filtered Fiche generated from the real 04-15-39049 working set."""
import json
import os

import pytest

from safety_eval import review_queue as rq
from safety_eval.config import Config
from safety_eval.fiche_parser import parse_fiche
from safety_eval.filtered_sheet import populate_filtered_sheet
from safety_eval.teaas import parse_crash_id_list, parse_import_list
from safety_eval.xlsx_patch import verify_integrity

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples", "04-15-39049")
TEMPLATE = os.path.join(
    HERE, "..", "templates", "Section Evaluation Workbook - 2023-12-04.xlsx")

needs_fixtures = pytest.mark.skipif(
    not os.path.exists(TEMPLATE), reason="fixtures not present")


# --- validation rules (docs/03) --------------------------------------------
def _det(status, new_mp=None, comment=None, cid="105904161"):
    return rq.Determination(crash_id=cid, status=status, new_mp=new_mp,
                            comment=comment)


def test_re_rejected_in_intersection_analysis():
    problems = rq.validate_determination(_det("RE", new_mp=1.5, comment="x"),
                                         "intersection")
    assert any("data error" in p for p in problems)


def test_re_requires_new_mp():
    assert rq.validate_determination(_det("RE"), "section")
    assert not rq.validate_determination(_det("RE", new_mp=17.7), "section")


def test_add_del_require_comment():
    assert rq.validate_determination(_det("ADD"), "section")
    assert rq.validate_determination(_det("DEL"), "section")
    assert not rq.validate_determination(
        _det("ADD", comment="at northern jct per coords"), "section")


def test_reviewed_nis_requires_comment_unreviewed_does_not():
    assert rq.validate_determination(_det("NIS"), "section", reviewed=True)
    assert not rq.validate_determination(_det("NIS"), "section",
                                         reviewed=False)
    assert not rq.validate_determination(
        _det("NIS", comment=">150'"), "section", reviewed=True)


def test_comment_style_no_em_dash():
    problems = rq.validate_determination(
        _det("NIS", comment="outside — per diagram"), "section")
    assert any("dash" in p for p in problems)


def test_section_suffix_statuses_accepted():
    assert not rq.validate_determination(
        _det("RE-2", new_mp=9.7, comment="x"), "section")
    assert not rq.validate_determination(_det("IS-2"), "section")
    assert rq.split_status("RE-2") == ("RE", "2")
    assert rq.split_status("IS") == ("IS", None)


def test_unknown_status_rejected():
    assert rq.validate_determination(_det("REV"), "section")
    assert rq.validate_determination(_det("MAYBE"), "intersection")


# --- GPS pre-screen ---------------------------------------------------------
def test_parse_coordinates_pipe_delimited():
    text = ("CRASH ID|ON RD CD|LATITUDE|LONGITUDE|\n"
            "105904161|30000091|35.65|-78.35|\n"
            "106001234|30000091|0|0|\n"           # missing coords dropped
            "bogus|x|1|2|\n")
    coords = rq.parse_coordinates(text)
    assert coords == {"105904161": (35.65, -78.35)}


def test_parse_coordinates_detailedfiche_xlsx(tmp_path):
    """The DetailedFiche (provided with the Original Fiche and Initial
    Study) as observed on 260412109EA_Fiche.xlsx: fiche columns A-I,
    J Crash ID, K Date, L-P T/C/F/L/S, Q Latitude, R Longitude, S Source."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "SomeFiche"
    ws = wb.create_sheet("DetailedFiche")
    ws.append(["Municipality", "On Road", "Miles", "Dir From", "From Road",
               "Toward Road", "Milepost Road", "MP", "MA", "Crash ID",
               "Date", "T", "C", "F", "L", "S",
               "Latitude", "Longitude", "Source"])
    ws.append(["RURAL", "SR 2453", 0.23, "SE", "SR 2444", "SR 2602",
               "SR 2453", 4.049, "Y", "108481213", "2026-04-12", 19, 1, 0, 1,
               "K", 35.445443, -80.61504, "DMV349"])
    ws.append(["RURAL", "SR 2444", 0, "", "SR 2453", "SR 2416", "SR 2444",
               2.645, "Y", 107723843, "2024-05-13", 28, 1, 0, 5,
               "O", 35.47265, -80.37112, "DMV349CLEANED"])
    ws.append(["RURAL", "NC 49", 0, "", "SR 2453", "SR 2444", "NC 49",
               20.423, "", 108372733, "2026-01-13", 30, 1, 7, 5,
               "C", None, None, None])          # no coords yet: skipped
    path = str(tmp_path / "fiche.xlsx")
    wb.save(path)

    coords = rq.parse_coordinates(path)
    assert coords == {"108481213": (35.445443, -80.61504),
                      "107723843": (35.47265, -80.37112)}
    # explicit sheet selection works too
    assert rq.parse_coordinates(path, sheet="DetailedFiche") == coords


def test_haversine_reasonable():
    # one degree of latitude is about 364,000 ft
    d = rq.haversine_ft(35.0, -78.0, 36.0, -78.0)
    assert 360_000 < d < 370_000
    assert rq.haversine_ft(35.0, -78.0, 35.0, -78.0) == 0.0


# --- sheet round trip on the real working set -------------------------------
@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    cfg = Config.load()
    fiche = parse_fiche(os.path.join(EX, "OriginalFiche.csv"))
    before = {c.crash_id for c in
              parse_crash_id_list(os.path.join(EX, "Before_ID.txt"), cfg)}
    after = {c.crash_id for c in
             parse_crash_id_list(os.path.join(EX, "After_ID.txt"), cfg)}
    mps = dict(parse_import_list(os.path.join(EX, "Before_Import.txt")))
    mps.update(parse_import_list(os.path.join(EX, "After_Import.txt")))
    out = str(tmp_path_factory.mktemp("wb") / "filtered.xlsx")
    populate_filtered_sheet(TEMPLATE, out, fiche, before, after, mps,
                            study_routes={"SR 1003"},
                            mp_range=(17.691, 17.811))
    return out


@needs_fixtures
def test_load_review_sheet_reads_generated_layout(workbook):
    review = rq.load_review_sheet(workbook)
    assert review.columns["crash_id"] == "L"
    assert review.columns["status"] == "I"
    assert review.columns["new_mp"] == "J"
    assert review.columns["comment"] == "S"
    in_study = [r for r in review.rows if r.banner == "IN STUDY"]
    assert len(in_study) == 59
    assert all(r.status in ("IS", "RE") for r in in_study)
    blanks = [r for r in review.rows if r.status is None]
    assert blanks, "review candidates must come back with blank statuses"


@needs_fixtures
def test_queue_orders_pending_first_and_flags_animals(workbook):
    review = rq.load_review_sheet(workbook)
    queue = rq.build_queue(review, mp_range=(17.691, 17.811))
    assert queue, "queue must not be empty"
    # pending rows strictly before determined rows
    pend = [i.pending for i in queue]
    assert pend.index(False) == pend.count(True)
    # animal crashes carry a skip reason
    for item in queue:
        if item.row.is_animal:
            assert item.skip_reason
    progress = rq.queue_progress(queue)
    assert progress["total"] == len(queue)
    assert progress["pending"] + progress["determined"] == len(queue)


@needs_fixtures
def test_apply_determinations_patches_only_target_cells(workbook, tmp_path):
    review = rq.load_review_sheet(workbook)
    pending = [r for r in review.rows if r.status is None]
    victim, other = pending[0], pending[1]
    out = str(tmp_path / "reviewed.xlsx")
    n = rq.apply_determinations(
        workbook, out,
        [rq.Determination(victim.crash_id, "NIS", comment=">150'")],
        analysis_type="section")
    assert n == 1
    assert verify_integrity(workbook, out).ok

    back = rq.load_review_sheet(out)
    by_id = back.by_id()
    assert by_id[victim.crash_id].status == "NIS"
    assert by_id[victim.crash_id].comment == ">150'"
    assert by_id[other.crash_id].status is None      # untouched
    # every other crash row survives unchanged
    assert len(back.rows) == len(review.rows)


@needs_fixtures
def test_apply_determinations_rejects_invalid(workbook, tmp_path):
    review = rq.load_review_sheet(workbook)
    cid = next(r.crash_id for r in review.rows)
    with pytest.raises(ValueError):
        rq.apply_determinations(
            workbook, str(tmp_path / "x.xlsx"),
            [rq.Determination(cid, "RE")],           # RE without New MP
            analysis_type="section")
    with pytest.raises(KeyError):
        rq.apply_determinations(
            workbook, str(tmp_path / "y.xlsx"),
            [rq.Determination("999999999", "NIS", comment="x")],
            analysis_type="section")


# --- audit trail ------------------------------------------------------------
def test_audit_trail_appends_and_reads_back(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    det = rq.Determination("105904161", "RE", new_mp=17.7,
                           comment="Remileposted from GPS coordinates; "
                                   "near SR 1003")
    rq.record_determination(path, det, previous=None)
    det2 = rq.Determination("105904161", "IS")
    prev = rq.ReviewRow(crash_id="105904161", row=5, status="RE", new_mp=17.7)
    rq.record_determination(path, det2, previous=prev)

    entries = rq.read_audit(path)
    assert len(entries) == 2
    assert entries[0]["status"] == "RE"
    assert entries[0]["previous_status"] is None
    assert entries[1]["previous_status"] == "RE"
    assert entries[1]["previous_new_mp"] == 17.7
    for e in entries:
        assert e["crash_id"] == "105904161"
        assert "ts" in e
    # the audit file is line-delimited json
    with open(path) as fh:
        for line in fh:
            json.loads(line)
