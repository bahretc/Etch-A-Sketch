"""qa_package: package-level deterministic QA (08-18-51363 (W-5708K), October 2026).

Every case here is a defect class that reached a live package: a TEAAS study
run on a partial crash ID list, a Complete Evaluation bound with a superseded
report of the same page count, reviewer deletions, and the Word one pager.
"""
import os
import shutil
import zipfile
from datetime import date, datetime

import openpyxl
import pytest

from safety_eval import qa_package as qp
from safety_eval.qa_checks import QaReport, volume_row
from safety_eval.teaas import parse_crash_id_list

# --------------------------------------------------------------------------- #
# synthetic TEAAS text in the layout pdftotext gives for an Intersection
# Analysis Report
# --------------------------------------------------------------------------- #
BANNER = ("                    North Carolina Department of Transportation\n"
          "                    Traffic Engineering Accident Analysis System\n"
          "                         Intersection Analysis Report\n")


def _listing(rows):
    return "".join(f" {i:>3}    {cid}      {d}           REAR END, SLOW OR STOP     $  1500   0  0\n"
                   f"                         14:56\n\n" for i, (cid, d) in enumerate(rows, 1))


def _report_pages(study, rows, start="11/01/2016", end="06/30/2021", adt=36700):
    summary = (BANNER + "                        Study Criteria Summary\n"
               f"Date:         {start}         to {end}                    Study:          {study}\n"
               f"Total Crashes                                    {len(rows)}              100.00\n")
    listing = BANNER + _listing(rows)
    criteria = (BANNER + "                                   Study Criteria\n"
                "Study Name                Log No.      PH No.     TIP No.     K/A Cf.   B/C Cf.   ADT\n"
                f"{study}       41000076576  081851363  w5708k  76.8   8.4   {adt}\n"
                "  Included Accidents\n" + "".join(f"    {cid}\n\n" for cid, _ in rows[:3]))
    tail = BANNER + "".join(f"       {cid}\n" for cid, _ in rows[3:])
    return [summary, listing, criteria, tail]


ROWS = [("104955337", "11/25/2016"), ("104954667", "11/26/2016"), ("104955211", "12/15/2016"),
        ("105367160", "01/09/2018"), ("105400028", "02/14/2018")]


def test_parse_teaas_pdf_text():
    rep = qp.parse_teaas_pdf_text("\f".join(_report_pages("41000076576BEFORE2", ROWS)))
    assert rep.study == "41000076576BEFORE2"
    assert (rep.start, rep.end) == (date(2016, 11, 1), date(2021, 6, 30))
    assert set(rep.listed) == {c for c, _ in ROWS} and rep.listed["105367160"] == date(2018, 1, 9)
    assert rep.included == {c for c, _ in ROWS}          # the list runs on to the next page
    assert rep.total == 5 and rep.adt == 36700


def test_parse_teaas_csv_text():
    text = ('"Date:","11/01/2016","to","06/30/2021","Study:","41000076576BEFORE2"\n'
            '"1","104955337","11/25/2016 10:57","SIDESWIPE, SAME DIRECTION","$","1550"\n'
            '"Unit","1",":","1","Alchl/Drgs:","0"\n'
            '"2","104954667","11/26/2016 19:11","RIGHT TURN, DIFFERENT ROADWAYS","$","1100"\n'
            '"Included Accidents"\n"104955337"\n"104954667"\n')
    rep = qp.parse_teaas_csv_text(text)
    assert rep.study == "41000076576BEFORE2" and rep.start == date(2016, 11, 1)
    assert set(rep.listed) == {"104955337", "104954667"} == rep.included


def test_appendix_start_finds_the_trailing_study_criteria_pages():
    pages = _report_pages("S", ROWS)
    assert qp._appendix_start(pages) == 2                   # criteria page and the ID tail
    assert qp._appendix_start(pages[:2]) == 2               # none: "Study Criteria Summary" only


# --------------------------------------------------------------------------- #
# compilation
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_pdfs(monkeypatch):
    """pdf_page_texts reads from this dict instead of poppler."""
    store = {}
    monkeypatch.setattr("safety_eval.print_results.pdf_page_texts", lambda p: store[p])
    return store


def _onepager_pages():
    return ["Safety Project Evaluation\nOrder ID: 41000076576 (2 of 2)\nTotal Crashes 46 70 52.17%",
            "Reductions in typical roadway volumes were experienced Statewide in 2020"]


def test_compilation_exact_with_appendix_left_out(fake_pdfs):
    before = _report_pages("B", ROWS)
    after = _report_pages("A", ROWS[:4], start="10/01/2021", end="05/31/2026")
    fake_pdfs.update({"op.pdf": _onepager_pages(), "b.pdf": before, "a.pdf": after,
                      "ce.pdf": _onepager_pages() + before[:2] + after[:2]})
    rep = qp.check_compilation("ce.pdf", ["op.pdf", "b.pdf", "a.pdf"])
    assert [f.severity for f in rep.findings] == ["Info"]
    assert "Study Criteria appendix" in rep.findings[0].claim and rep.ok


def test_compilation_with_a_superseded_report_of_the_same_page_count(fake_pdfs):
    """The 2 of 2 Complete Evaluation still held the 72-crash AFTER2: same
    page count as the 70-crash report, different crash listing pages."""
    current = _report_pages("A", ROWS[:4], start="10/01/2021", end="05/31/2026")
    stale = _report_pages("A", ROWS, start="10/01/2021", end="05/31/2026")
    fake_pdfs.update({"op.pdf": _onepager_pages(), "a.pdf": current, "ce.pdf": _onepager_pages() + stale})
    rep = qp.check_compilation("ce.pdf", ["op.pdf", "a.pdf"])
    assert len(fake_pdfs["ce.pdf"]) == 2 + len(current)          # a page count check passes
    claims = [f.claim for f in rep.findings if f.severity == "High"]
    assert any("not in the compilation" in c for c in claims)
    assert any("match none of the parts" in c for c in claims)
    assert not rep.ok


def test_compilation_order(fake_pdfs):
    b = _report_pages("B", ROWS)[:2]
    a = _report_pages("A", ROWS[:2], start="10/01/2021", end="05/31/2026")[:2]
    fake_pdfs.update({"b.pdf": b, "a.pdf": a, "ce.pdf": a + b})
    rep = qp.check_compilation("ce.pdf", ["b.pdf", "a.pdf"])
    assert any("order" in f.claim for f in rep.findings)


# --------------------------------------------------------------------------- #
# TEAAS study versus the workbook period sheet
# --------------------------------------------------------------------------- #
def _rows(ids, t=21, s="O"):
    return {cid: qp.PeriodRow(cid, datetime.strptime(d, "%m/%d/%Y").date(), t, s) for cid, d in ids}


def _crash_list(ids, t=21, svr=5):
    return "CRASH ID|ON RD CD|SVRTY|DATE|TYPE|\n" + "".join(f"{c}||{svr}|{d} 10:00|{t}|\n" for c, d in ids)


def test_study_partial_pdf_names_the_missing_crashes():
    """BEFORE2 as first delivered: the PDF held 20 of the 46 crashes."""
    st = qp.TeaasStudy("41000076576BEFORE2")
    st.reports["pdf"] = qp.parse_teaas_pdf_text("\f".join(_report_pages("41000076576BEFORE2", ROWS[:2])))
    st.id_list = "x"
    st.id_rows = {c.crash_id: c for c in parse_crash_id_list(_crash_list(ROWS))}
    rep = qp.check_study(st, _rows(ROWS), "before", (date(2016, 11, 1), date(2021, 6, 30)), label="2 of 2")
    claims = [f.claim for f in rep.findings]
    assert any("exports disagree" in c for c in claims)
    hit = next(f for f in rep.findings if "TEAAS pdf: 3 of the 5" in f.claim)
    assert "105367160" in hit.evidence and "last crash listed 11/26/2016" in hit.evidence
    assert not any("CrashID list:" in c and "not in the study" in c for c in claims)


def test_study_extra_crash_dates_and_fields():
    st = qp.TeaasStudy("41000076576AFTER2")
    st.reports["pdf"] = qp.parse_teaas_pdf_text("\f".join(_report_pages("41000076576AFTER2", ROWS,
                                                                        start="10/01/2021", end="04/30/2026")))
    st.id_list = "x"
    st.id_rows = {c.crash_id: c for c in parse_crash_id_list(_crash_list(ROWS, t=30, svr=4))}
    rows = _rows(ROWS[:4])
    rep = qp.check_study(st, rows, "after", (date(2021, 10, 1), date(2026, 5, 31)))
    claims = " | ".join(f.claim + " " + f.evidence for f in rep.findings)
    assert "1 crash(es) in the study are not on the workbook after sheet" in claims and "105400028" in claims
    assert "study dates 10/01/2021 to 04/30/2026 differ" in claims
    assert "T 21 vs TEAAS 30" in claims and "severity O vs TEAAS C" in claims


def test_study_clean():
    st = qp.TeaasStudy("S")
    st.reports["pdf"] = qp.parse_teaas_pdf_text("\f".join(_report_pages("S", ROWS)))
    st.id_list = "x"
    st.id_rows = {c.crash_id: c for c in parse_crash_id_list(_crash_list(ROWS))}
    rep = qp.check_study(st, _rows(ROWS), "before", (date(2016, 11, 1), date(2021, 6, 30)))
    assert not rep.findings and "5 TEAAS crashes vs 5 on the sheet" in rep.verified[0]


# --------------------------------------------------------------------------- #
# reviewer comments
# --------------------------------------------------------------------------- #
COMMENTS = """Intersection 28
*\tRemove comma between (LTSR) and Crashes in target crashes field
*\tProject Development was not filled out
*\tCrash 108167818 occurred at the Biscuitville driveway and so there is not a target
\t*\tMake sure to update additional table
Intersection 29
*\tDelete Crashes
\t*\t106926706 - looks like it occurred fully in the PVA
\t*\t105439017 -  looks like it could here: https://maps.app.goo.gl/7RXnFeh78e4bvT936
\t*\t107570036 – at stop sign
*\tAdd a comment on the A injury crash in the after period.
*\tSee crash 106000001 for the red light running
"""


def test_reviewer_crash_requests():
    got = {r["crash_id"]: r["action"] for r in qp.reviewer_crash_requests(COMMENTS)}
    assert got == {"108167818": "not_target", "106926706": "delete", "105439017": "delete",
                   "107570036": "delete", "106000001": "mention"}


# --------------------------------------------------------------------------- #
# workbook and one pager fixtures (shapes of the accessible xlsm and the
# macro's Word output; no client data)
# --------------------------------------------------------------------------- #
def _accessible_workbook(path, before, after, target=(), onepager_date="10/7/2026", blank_s=()):
    wb = openpyxl.Workbook()
    wb.active.title = "Assumptions"
    a = wb["Assumptions"]
    a["K11"], a["L11"], a["Q11"] = "Leg", "Road", "Alt Text (Copy each row into the Alt Text for the Map)"
    a["K12"], a["L12"], a["Q12"] = "East", "US 64 Business", "East leg: US 64 Business, 45 mph, 2023 AADT: 31500"
    a["K13"], a["L13"], a["Q13"] = "South", "Plaza Drive", "South leg: Plaza Drive, no posted speed limit, 2023 AADT: 9400 (est)"
    a["Q14"] = " leg: ,  mph,  AADT: "
    for name, rows, period in (("Before", before, "Before Period (11/01/16 - 06/30/21)"),
                               ("After", after, "After Period (10/01/21 - 05/31/26)")):
        ws = wb.create_sheet(name)
        ws["A2"] = period
        ws.append([])
        for c, h in enumerate(["Crash ID", "Date", "T", "C", "F", "L", "S", "Analyst Notes Column 1",
                               "Analyst Notes Column 2", "Analyst Notes Column 3", "Analyst Notes Column 4",
                               "Target-1?", "Target-2?", "Target-3?", "", "Crash #", "Total", "Target-1"], 1):
            ws.cell(3, c, h)
        for i, (cid, d) in enumerate(rows, 4):
            ws.cell(i, 1, int(cid))
            ws.cell(i, 2, datetime.strptime(d, "%m/%d/%Y"))
            ws.cell(i, 3, 21)
            ws.cell(i, 7, None if cid in blank_s else "O")
            if cid in target:
                ws.cell(i, 12, "Y")
    op = wb.create_sheet("One Pager")
    op["H3"], op["I3"] = "Order ID:", "41000076576 (2 of 2)"
    op["H4"], op["I4"] = "Project ID:", "08-18-51363 (TIP #W-5708K)"
    op["H24"], op["I24"] = "Date:", onepager_date
    op["K13"], op["L13"], op["M13"] = "Additional Information", "Before", "After"
    op["K15"], op["L15"], op["M15"], op["N15"] = "Rear End Crashes", "3.64 cpy (17)", "7.07 cpy (33)", 0.941176470588235
    op["AF4"], op["AG4"], op["AH4"] = "Treatment Information", "Before", "After"
    op["AF6"], op["AG6"], op["AH6"], op["AI6"] = "Total Crashes", 46, 70, 0.521739130434783
    op["AF7"], op["AG7"], op["AH7"], op["AI7"] = "Total Severity Index", 3.73, 3.35, -0.101876675603217
    op["AF12"], op["AG12"], op["AH12"], op["AI12"] = "Volume (2018, 2023)", 36700, 36200, -0.0136239782
    op["K30"], op["L30"], op["M30"], op["N30"] = "Start Date", datetime(2012, 11, 1), datetime(2016, 11, 1), datetime(2021, 10, 1)
    wb.save(path)
    return path


def _p(text):
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _row(*cells):
    return "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in cells) + "</w:tr>"


def _onepager_docx(path, *, date_text="10/7/2026", volume=("36,700", "36,200", "-1.36%"),
                   total=("46", "70", "52.17%"), alt="East leg: US 64 Business, 45 mph, 2023 AADT: 31500&#10;"
                   "South leg: Plaza Drive, no posted speed limit, 2023 AADT: 9400 (est)",
                   extra_paragraphs=()):
    body = (_p("Order ID: 41000076576 (2 of 2)") + _p("Completion Date: 8/19/2021")
            + "<w:tbl>" + _row("", "Project Development", "Before Period", "After Period")
            + _row("Start Date", "11/1/2012", "11/1/2016", "10/1/2021") + "</w:tbl>"
            + "<w:tbl>" + _row("Treatment Information", "Before", "After", "Percent")
            + _row("Total Crashes", *total) + _row("Total Severity Index", "3.73", "3.35", "-10.19%")
            + _row("Volume (2018, 2023)", *volume) + "</w:tbl>"
            + "<w:tbl>" + _row("Additional Information", "Before", "After", "Percent")
            + _row("Rear End Crashes", "3.64 cpy (17)", "7.07 cpy (33)", "94.12%") + "</w:tbl>"
            + "".join(_p(t) for t in extra_paragraphs)
            + _p(f"North Carolina Department of Transportation Date: {date_text}")
            + '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="5000000" cy="3000000"/>'
            + f'<wp:docPr id="1" name="Picture 1" descr="{alt}"/></wp:inline></w:drawing></w:r></w:p>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def test_same_value():
    assert qp.same_value("36,700", 36700) and qp.same_value("-10.19%", -0.101876675603217)
    assert qp.same_value("3.73", 3.7285714) and not qp.same_value("3.80", 3.73)
    assert qp.same_value("100+%", "100+%") and qp.same_value("11/1/2016", datetime(2016, 11, 1))
    assert qp.same_value("n/a", None) and not qp.same_value("52.17%", 0.6)


def test_onepager_docx_clean(tmp_path):
    wb = _accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:3], ROWS[3:])
    rep = qp.check_onepager_docx(_onepager_docx(str(tmp_path / "op.docx")), wb)
    # the map picture is a package check (check_workbook_map); nothing is wrong here
    assert [f.claim for f in rep.findings] == []
    assert any("4 table rows compared" in v and "0 differ" in v for v in rep.verified)


def test_onepager_docx_defects(tmp_path):
    wb = _accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:3], ROWS[3:])
    docx = _onepager_docx(str(tmp_path / "op.docx"), date_text="9/24/2026", volume=("36,700", "36,900", "0.5%"),
                          total=("46", "72", "56.52%"), alt="Aerial view of the intersection",
                          extra_paragraphs=("Prepared from the TEAAS report and the workbook — see 2X",
                                            "The A injury crash happened at 3:39 PM."))
    rep = qp.check_onepager_docx(docx, wb)
    text = " | ".join(f"[{f.severity}] {f.claim}" for f in rep.findings)
    assert "[High] template placeholder '2X'" in text
    assert "date 09/24/2026 differs from the workbook One Pager date 10/07/2026" in text
    assert "volume row shows" in text and "row 'Total Crashes' shows" in text
    assert "map alt text is not the Assumptions alt text rows verbatim" in text
    assert "em dash" in text and "names 'TEAAS'" in text and "names 'workbook'" in text
    assert "[Low] time of day in the text" in text


def test_onepager_docx_missing_alt_text_and_stale_pdf(tmp_path, monkeypatch):
    docx = _onepager_docx(str(tmp_path / "op.docx"), alt="")
    monkeypatch.setattr(qp, "_pdf_reading_text", lambda p: "Order ID: 41000076576 (2 of 2)\nCompletion Date:")
    rep = qp.check_onepager_docx(docx, pdf="op.pdf")
    claims = [f.claim for f in rep.findings]
    assert any("no alt text" in c for c in claims)
    assert any(c.startswith("the PDF does not match") for c in claims)


def test_volume_row_reads_the_accessible_one_pager(tmp_path):
    wb = openpyxl.load_workbook(_accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:1], ROWS[1:2]))
    assert volume_row(wb) == ("Volume (2018, 2023)", 36700, 36200)


# --------------------------------------------------------------------------- #
# whole package
# --------------------------------------------------------------------------- #
def _package(tmp_path, *, before=ROWS[:3], after=ROWS[3:], target=(), with_deleted=()):
    root = tmp_path / "WO-41000076576 08-18-51363 (W-5708K)"
    ca = root / "Crash Analysis"
    ca.mkdir(parents=True)
    (root / "Notes").mkdir()
    _accessible_workbook(str(ca / "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx"),
                         list(before) + list(with_deleted), after, target=target)
    (ca / "41000076576BEFORE2_CrashID.txt").write_text(_crash_list(list(before) + list(with_deleted)))
    (ca / "41000076576AFTER2_CrashID.txt").write_text(_crash_list(after))
    (ca / "~$Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx").write_bytes(b"\x0bChris")
    _onepager_docx(str(ca / "08-18-51363 (W-5708K) 2 of 2 One Pager.docx"))
    return str(root)


def test_discovery_ignores_hidden_office_files(tmp_path):
    lay = qp.discover_package(_package(tmp_path))
    assert not any("~$" in f for f in lay.files)
    (loc,) = lay.locations
    assert loc.label == "2 of 2" and loc.workbook.endswith("2 of 2.xlsx") and loc.onepager_docx
    assert {k: s.name for k, s in loc.studies.items()} == {"before": "41000076576BEFORE2",
                                                          "after": "41000076576AFTER2"}


def test_run_package_qa_traces_reviewer_requests(tmp_path):
    root = _package(tmp_path, target=("104955337",), with_deleted=(("106926706", "03/03/2020"),))
    comments = ("Crash 104955337 occurred at the driveway and so there is not a target\n"
                "Delete Crashes\n 106926706 - fully in the PVA\n 105439017 - at stop sign\n")
    pq = qp.run_package_qa(root, comments=comments)
    highs = [f for f in pq.report.findings if f.severity == "High"]
    assert any("106926706" in f.where and "deleted" in f.claim and "2 of 2 before" in f.claim for f in highs)
    assert any("104955337" in f.where and "not a target" in f.claim for f in highs)
    assert any("105439017: deleted as the reviewer asked" in v for v in pq.report.verified)
    assert not any("~$" in (f.where + f.claim) for f in pq.report.findings)
    assert "Crashes named in the reviewer's comments" in pq.facts_text()
    assert any("no complete evaluation found" in f.claim for f in pq.report.findings)


def test_run_package_qa_reads_comments_from_notes(tmp_path):
    root = _package(tmp_path, with_deleted=(("106926706", "03/03/2020"),))
    eml = ("Subject: RE: Safety Evaluation\nContent-Type: text/plain\n\n"
           "Delete Crashes\n 106926706 - fully in the PVA\n")
    with open(os.path.join(root, "Notes", "review.eml"), "w") as fh:
        fh.write(eml)
    pq = qp.run_package_qa(root)
    assert any("106926706" in f.where for f in pq.report.findings)


def test_second_workbook_for_a_location_is_flagged(tmp_path):
    root = _package(tmp_path)
    shutil.copy(os.path.join(root, "Crash Analysis",
                             "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx"),
                os.path.join(root, "Crash Analysis", "Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx"))
    pq = qp.run_package_qa(root)
    assert any("a second evaluation workbook" in f.claim for f in pq.report.findings)


def test_cli_qa_package(tmp_path, capsys):
    from safety_eval.cli import main as cli_main

    root = _package(tmp_path)
    out = str(tmp_path / "qa.md")
    rc = cli_main(["qa", "--package", root, "--output", out])
    assert rc == 1                                  # no Complete Evaluation: Medium findings
    assert "no complete evaluation found" in capsys.readouterr().out
    with open(out) as fh:
        md = fh.read()
    assert md.startswith("# Package QA checks") and "41000076576BEFORE2" in md


# --------------------------------------------------------------------------- #
# cached values versus a recalculation (needs LibreOffice)
# --------------------------------------------------------------------------- #
TEMPLATE = "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx"


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")) or not os.path.exists(TEMPLATE),
                    reason="LibreOffice or the template is not available")
def test_cached_values_catch_a_stale_cache(tmp_path):
    import re

    from safety_eval.xlsx_patch import sheet_files

    clean = qp.check_cached_values(TEMPLATE, sheets=("Evaluation Set-up",))
    assert not clean.findings
    member = sheet_files(TEMPLATE)["Evaluation Set-up"]
    out = str(tmp_path / "stale.xlsx")
    with zipfile.ZipFile(TEMPLATE) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == member:
                xml = data.decode("utf-8")
                m = re.search(r'(<c r="([A-Z]+\d+)"(?:\s+[\w:]+="[^"]*")*\s*><f>[^<]*</f><v>)(-?\d+(?:\.\d+)?)(</v>)', xml)
                assert m, "a numeric formula cell in Evaluation Set-up"
                xml = xml[:m.start(3)] + "987654" + xml[m.end(3):]
                data = xml.encode("utf-8")
            zout.writestr(info, data)
    rep = qp.check_cached_values(out, sheets=("Evaluation Set-up",))
    assert any(m.group(2) in f.where and "987654" in f.evidence for f in rep.findings)


def test_blank_severity_assumptions(tmp_path):
    wb = _accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:3], ROWS[3:], blank_s=("104954667",))
    assert qp.blank_severity_assumptions(wb) == {"Before": {"G5": "O"}}


def test_hidden_files():
    assert qp.is_hidden("~$Book.xlsx") and qp.is_hidden("/a/b/.DS_Store") and not qp.is_hidden("Book.xlsx")


# --------------------------------------------------------------------------- #
# what the 08-18-51363 package audit found after the first pass: the map's alt
# text lost in the PDF export, the macro's template path on a consultant
# share, draft markers left in crash notes
# --------------------------------------------------------------------------- #
def _tagged_pdf(path, alt=None, tagged=True, role="/Figure"):
    pikepdf = pytest.importorskip("pikepdf")
    pdf = pikepdf.new()
    pdf.add_blank_page()
    fig = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name(role))
    if alt is not None:
        fig.Alt = pikepdf.String(alt)
    fig = pdf.make_indirect(fig)
    doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Document"),
                                               K=pikepdf.Array([fig])))
    st = pikepdf.Dictionary(Type=pikepdf.Name("/StructTreeRoot"), K=doc,
                            RoleMap=pikepdf.Dictionary(InlineShape=pikepdf.Name("/Figure")))
    pdf.Root.StructTreeRoot = pdf.make_indirect(st)
    if tagged:
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.save(path)
    return path


def test_pdf_figure_without_alt_text(tmp_path):
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "op.pdf"), alt=None))
    assert [f.severity for f in rep.findings] == ["High"] and "no alternate text" in rep.findings[0].claim
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "ok.pdf"), alt="East leg: US 64 Business"))
    assert not rep.findings
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "r.pdf"), alt="", role="/InlineShape"))
    assert any("no alternate text" in f.claim for f in rep.findings)        # role-mapped to Figure
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "u.pdf"), alt="x", tagged=False))
    assert [f.severity for f in rep.findings] == ["High"] and "not tagged" in rep.findings[0].claim
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "c.pdf"), alt="", tagged=False), public=False)
    assert [f.severity for f in rep.findings] == ["Info"]


def test_template_path_and_draft_markers(tmp_path):
    root = _package(tmp_path)
    wbp = os.path.join(root, "Crash Analysis",
                       "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx")
    wb = openpyxl.load_workbook(wbp)
    wb["One Pager"]["I26"] = "\\\\consultant.com\\gbl\\Client\\Accessible Worksheets"
    wb["Before"]["J5"] = "failed to yield from driveway; verify"
    wb.save(wbp)
    pq = qp.run_package_qa(root)
    by_where = {f.where: f for f in pq.report.findings}
    assert "Template Path" in by_where["2 of 2 One Pager!I26"].claim
    assert qp.NCDOT_TEMPLATE_PATH in by_where["2 of 2 One Pager!I26"].fix
    notes = by_where["2 of 2 Before/After notes"]
    assert notes.severity == "Low" and "Before 104954667" in notes.evidence
    wb = openpyxl.load_workbook(wbp)
    wb["One Pager"]["I26"] = qp.NCDOT_TEMPLATE_PATH
    wb.save(wbp)
    assert "2 of 2 One Pager!I26" not in {f.where for f in qp.run_package_qa(root).report.findings}



# --------------------------------------------------------------------------- #
# regressions from the adversarial review of this module (October 2026)
# --------------------------------------------------------------------------- #
def test_pdf_rows_stay_on_one_line_and_allow_a_milepost():
    appendix = ("  Included Accidents\n    108494396\n\n    108153584\n"
                "07/31/2026     All data presented in this report comes explicitly from the\n")
    rep = qp.parse_teaas_pdf_text(appendix)
    assert rep.listed == {} and rep.included == {"108494396", "108153584"}
    strip = "   1    107822778    1.413    08/18/2024     OVERTURN/ROLLOVER    $  9500\n"
    assert qp.parse_teaas_pdf_text(strip).listed == {"107822778": date(2024, 8, 18)}


def test_strip_csv_has_a_milepost_column():
    text = ('"Date:","7/1/2021","to","6/30/2026","Study:","41000079307"\n'
            '"1","107822778","1.413","08/18/2024 05:08","OVERTURN/ROLLOVER","$","9500","0"\n'
            '"2","107900001","1.52","09/01/2024 11:00","REAR END, SLOW OR STOP","$","1200","0"\n')
    rep = qp.parse_teaas_csv_text(text)
    assert rep.listed == {"107822778": date(2024, 8, 18), "107900001": date(2024, 9, 1)}


def test_included_and_excluded_accidents():
    """Included Accidents are the crashes forced in (all for an import-list
    run, a few for a criteria run); Excluded ones must not be analysed."""
    csv_text = ('"1","104955337","11/25/2016 10:57","ANGLE"\n"2","104954667","11/26/2016 19:11","ANGLE"\n'
                '"Included Accidents"\n"104955337"\n"Excluded Accidents"\n"106926706"\n')
    r = qp.parse_teaas_csv_text(csv_text)
    assert r.included == {"104955337"} and r.excluded == {"106926706"}
    st = qp.TeaasStudy("S")
    st.reports["csv"] = r
    rows = _rows([("104955337", "11/25/2016"), ("104954667", "11/26/2016")])
    assert not qp.check_study(st, rows, "before", None).findings          # a criteria run is fine
    r.included.add("105000001")
    r.listed["106926706"] = date(2020, 3, 3)
    rows["106926706"] = qp.PeriodRow("106926706", date(2020, 3, 3), 21, "O")
    claims = [f.claim for f in qp.check_study(st, rows, "before", None).findings]
    assert any("Included Accidents were not analysed" in c for c in claims)
    assert any("Excluded Accidents are still analysed" in c for c in claims)


def test_summary_column_is_not_a_target_flag(tmp_path):
    p = _accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:3], ROWS[3:])
    wb = openpyxl.load_workbook(p)
    wb["Before"]["R4"] = 1                       # "Target-1" summary block, not the "Target-1?" flag
    wb.save(p)
    assert qp.read_workbook_facts(p).periods["before"][ROWS[0][0]].targets == ()


def test_full_workbook_naming_groups_id_lists_with_reports(tmp_path, fake_pdfs, monkeypatch):
    root = tmp_path / "WO-1 05-08-203 (W-5601HP)"
    ca = root / "Crash Analysis"
    (ca / "Superseded").mkdir(parents=True)
    _accessible_workbook(str(ca / "Intersection Evaluation Workbook - 05-08-203.xlsx"), ROWS[:3], ROWS[3:])
    (ca / "Before_ID.txt").write_text(_crash_list(ROWS[:3]))
    (ca / "After_ID.txt").write_text(_crash_list(ROWS[3:]))
    (ca / "InitialID.txt").write_text(_crash_list(ROWS))
    (ca / "Superseded" / "After_ID.txt").write_text(_crash_list(ROWS[3:4]))
    lay = qp.discover_package(str(root))
    (loc,) = lay.locations
    assert {k: s.name for k, s in loc.studies.items()} == {"before": "Before", "after": "After"}
    assert [s.name for s in lay.initial] == ["Initial"]
    (second,) = [s for s, slot in lay.unmatched]
    assert second.name.startswith("After (") and "Superseded" in second.name
    pq = qp.run_package_qa(str(root))
    assert any("a second study for the after period; After was checked" in f.claim for f in pq.report.findings)
    assert any("initial study" in v for v in pq.report.verified)


def test_compilation_page_that_changed_after_binding(fake_pdfs):
    op_now = _onepager_pages()
    op_bound = [op_now[0].replace("52.17%", "57.14%")] + op_now[1:]
    fake_pdfs.update({"op.pdf": op_now, "ce.pdf": op_bound})
    rep = qp.check_compilation("ce.pdf", ["op.pdf"], threshold=0.5)
    hit = next(f for f in rep.findings if "differs from op.pdf page 1" in f.claim)
    assert "57.14%" in hit.evidence and "52.17%" in hit.evidence


def _workbook_with_injury_tables(path):
    p = _accessible_workbook(path, ROWS[:3], ROWS[3:])
    wb = openpyxl.load_workbook(p)
    op = wb["One Pager"]
    for r0, title, vals in ((14, "Injury Crash Summary", (12, 7, -0.416666666666667, 29, 57, 0.96551724137931)),
                            (22, "Target Injury Crash Summary", (3, 2, -0.333333333333333, 3, 11, "100+%"))):
        op.cell(r0, 32, title)
        op.cell(r0 + 2, 32, "Class C Injury Crashes")
        op.cell(r0 + 3, 32, "Property Damage Only")
        for k in range(3):
            op.cell(r0 + 2, 33 + k, vals[k])
            op.cell(r0 + 3, 33 + k, vals[3 + k])
    wb.save(p)
    return p


def test_docx_tables_are_compared_with_their_own_block(tmp_path):
    wb = _workbook_with_injury_tables(str(tmp_path / "w.xlsx"))
    good = ("<w:tbl>" + _row("Target Injury Crash Summary", "Before", "After", "Pct")
            + _row("Class C Injury Crashes", "3", "2", "-33.33%") + _row("Property Damage Only", "3", "11", "100+%")
            + "</w:tbl>")
    swapped = ("<w:tbl>" + _row("Target Injury Crash Summary", "Before", "After", "Pct")
               + _row("Class C Injury Crashes", "12", "7", "-41.67%") + _row("Property Damage Only", "29", "57", "96.55%")
               + "</w:tbl>")
    for body, expect in ((good, 0), (swapped, 2)):
        path = str(tmp_path / f"op{expect}.docx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body>' + body + "</w:body></w:document>")
        rep = qp.check_onepager_docx(path, wb)
        assert len([f for f in rep.findings if f.claim.startswith("row ")]) == expect


REPO_WB = "deliverables/05-20-62123/Accessible Intersection Evaluation Workbook - 05-20-62123 (HS-2005A).xlsm"
REPO_DOCX = "deliverables/05-20-62123/41000076579_OnePager.docx"


@pytest.mark.skipif(not os.path.exists(REPO_WB), reason="05-20-62123 deliverable not present")
def test_workbook_picture_without_alt_text(tmp_path):
    import re

    out = str(tmp_path / "wb.xlsm")
    with zipfile.ZipFile(REPO_WB) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("xl/drawings/drawing") and info.filename.endswith(".xml"):
                data = re.sub(rb'(<xdr:cNvPr\b[^>]*?)\s+descr="[^"]*"', rb"\1", data)
            zout.writestr(info, data)
    rep = QaReport()
    qp.check_workbook_map(qp.read_workbook_facts(out), rep)
    assert any(f.severity == "High" and "has no alt text" in f.claim for f in rep.findings)
    clean = QaReport()
    qp.check_workbook_map(qp.read_workbook_facts(REPO_WB), clean, qp.read_docx_facts(REPO_DOCX).images)
    assert not clean.findings
    assert not any(f.severity in ("High", "Medium") for f in qp.check_onepager_docx(REPO_DOCX, REPO_WB).findings)


def test_pdf_numbers_must_match_the_docx(tmp_path, monkeypatch):
    docx = _onepager_docx(str(tmp_path / "op.docx"), total=("46", "70", "100+%"))
    pdf_text = "\n".join(qp.read_docx_facts(docx).paragraphs).replace("100+%", "52.17%")
    monkeypatch.setattr(qp, "_pdf_reading_text", lambda p: pdf_text)
    rep = qp.check_onepager_docx(docx, pdf="op.pdf")
    hit = next(f for f in rep.findings if "does not match" in f.claim)
    assert "100+%" in hit.evidence and "0 paragraph(s)" in hit.claim
    monkeypatch.setattr(qp, "_pdf_reading_text", lambda p: "\n".join(qp.read_docx_facts(docx).paragraphs))
    assert not any("does not match" in f.claim for f in qp.check_onepager_docx(docx, pdf="op.pdf").findings)


def test_deleted_crash_still_printed_in_the_complete_evaluation(tmp_path, fake_pdfs):
    root = _package(tmp_path)
    ce = os.path.join(root, "08-18-51363 (W-5708K) 2 of 2 Complete Evaluation.pdf")
    open(ce, "wb").close()
    fake_pdfs[ce] = ["Report\n  25   107259626    03/01/2023   REAR END, SLOW OR STOP\n"]
    pq = qp.run_package_qa(root, comments="Delete Crashes\n* 107259626 - fully in the PVA\n")
    hit = next(f for f in pq.report.findings if "107259626" in f.where)
    assert "Complete Evaluation.pdf" in hit.claim


@pytest.mark.parametrize("text,expected", [
    ("Remove crash 108167818 from the target crashes", {"108167818": "not_target"}),
    ("Please remove 108167818 as a target crash", {"108167818": "not_target"}),
    ("Crashes 105509762 and 105034665 are not targets", {"105509762": "not_target", "105034665": "not_target"}),
    ("Delete crashes:\n105509762 - at stop sign\n\n* Please add a comment on crash 108494396 (A injury)",
     {"105509762": "delete", "108494396": "mention"}),
])
def test_reviewer_phrasings(text, expected):
    assert {r["crash_id"]: r["action"] for r in qp.reviewer_crash_requests(text)} == expected


def test_cached_strings_decode_every_entity():
    assert qp._cached("str", "a&#10;b &quot;48&quot; &amp; c", []) == 'a\nb "48" & c'


def test_cli_exit_status_includes_the_package_report(tmp_path):
    from safety_eval.cli import main as cli_main

    root = _package(tmp_path)
    wbp = os.path.join(root, "Crash Analysis",
                       "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx")
    assert cli_main(["qa", "--package", root, "--workbook", wbp]) == 1


def test_missing_or_empty_package_is_not_a_clean_bill(tmp_path):
    with pytest.raises(FileNotFoundError):
        qp.run_package_qa(str(tmp_path / "no such folder"))
    (tmp_path / "WO-1 empty").mkdir()
    rep = qp.run_package_qa(str(tmp_path / "WO-1 empty")).report
    assert not rep.ok and "no evaluation workbook" in rep.findings[0].claim



# --------------------------------------------------------------------------- #
# rules review (CLAUDE.md rules 6, 10, 11; docs/05)
# --------------------------------------------------------------------------- #
def test_public_text_rules():
    rep = QaReport()
    paras = ["Target Crashes: Frontal Impact Crashes: Angle, Left Turn Same Roadway (LTSR), LTDR and RTSR crashes",
             "Both crashes occurred in the traffic circle; Oak Circle is the side street.",
             "Two crashes had no severity codes and three were PDO; the fiches agree.",
             "The crash occurred at about 3 PM.", "The 4-5 PM hour went from 0 to 15 crashes.",
             "Signal updated in the Plans of Record - no phasing changes (8/19/2021, 9/8/2023)."]
    qp.check_public_text(paras, "op", rep, discussion=paras[3:], skip_dates=(date(2021, 8, 19),))
    text = " | ".join(f"[{f.severity}] {f.claim} {f.evidence}" for f in rep.findings)
    assert "'LTDR' in the target crash text is not spelled out" in text and "'RTSR'" in text
    assert "'LTSR'" not in text
    assert "'traffic circle': a roundabout is never called a circle" in text and "Oak Circle'" not in text
    assert "names 'severity codes'" in text and "names 'PDO'" in text and "names 'fiches'" in text
    assert text.count("time of day in the text") == 1 and "about 3 PM" in text
    assert "spaced hyphen" in text and "[Info] 1 date(s) in Items for Discussion" in text and "9/8/2023" in text


def test_untagged_one_pager_pdf_is_high(tmp_path):
    rep = qp.check_pdf_accessibility(_tagged_pdf(str(tmp_path / "p.pdf"), alt="x", tagged=False))
    assert rep.findings[0].severity == "High" and "Saved As PDF" in rep.findings[0].claim


def test_workbook_map_checks(tmp_path):
    f = qp.read_workbook_facts(_accessible_workbook(str(tmp_path / "w.xlsx"), ROWS[:1], ROWS[1:2]))
    rep = QaReport()
    qp.check_workbook_map(f, rep, docx_images=[])
    claims = [(x.severity, x.claim) for x in rep.findings]
    assert ("Medium", "no picture on the Assumptions sheet (Map/Satellite Views, rule 10)") in claims
    assert ("High", "the one pager has no Map/Satellite View image") in claims


def test_template_path_is_low(tmp_path):
    root = _package(tmp_path)
    wbp = os.path.join(root, "Crash Analysis",
                       "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx")
    wb = openpyxl.load_workbook(wbp)
    wb["One Pager"]["I26"] = "\\\\consultant.com\\share"
    wb.save(wbp)
    f = next(x for x in qp.run_package_qa(root).report.findings if x.where.endswith("I26"))
    assert f.severity == "Low"


def test_reviewer_negations():
    got = {r["crash_id"]: r["action"] for r in qp.reviewer_crash_requests(
        "* Do not delete crash 106754327, it is within 150 ft.\n* Delete Crashes\n\t* 123456780 - in the PVA\n\n"
        "\t* 106758298 should stay a target crash; keep it.\nCrash 123456789 should not be a target.\n")}
    assert got == {"106754327": "mention", "123456780": "delete", "106758298": "mention", "123456789": "not_target"}


def test_package_report_paths_are_relative(tmp_path):
    root = _package(tmp_path)
    pq = qp.run_package_qa(root)
    assert not any(root in v for v in pq.report.verified)
    assert not any(root in (f.where + f.claim + f.evidence) for f in pq.report.findings)
