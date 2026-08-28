"""Fatal slip parsing and Field Investigation File generation.

The slip fixture mirrors the layout of a real NCDOT Fatal Crash
Notification (M260408001 was the reference; the fixture's facts are
synthetic). The checklist layout and vocabulary follow docs/02 and the
completed TSUINT596369 sheet."""
import openpyxl
import pytest

from safety_eval import field_investigation as fi

SLIP_TEXT = """\
                             NCDOT Fatal Crash Notification

     Internal ID/Fatal Slip Number: M269901001                   Crash Date: 4/8/2026
                            Crash ID: 108000001                  Crash Time: 6:22:00 PM
Crashweb Link for Report Image:
       https://crashweb.ncdot.gov/crashweb/submitCrashIDFromTRCS.do?crashID=108000001

Location
Division 10 | Metrolina Region
Union County, in Stallings
On *LCL MAPLE RD, 0 miles from *LCL BIRCH LN toward *
https://www.google.com/maps/place/35.097566+-80.67566

Description
UNIT ONE WAS TRAVELING SOUTHWEST ON MAPLE ROAD WHEN UNIT TWO ENTERED THE
INTERSECTION. THE VEHICLES COLLIDED IN THE INTERSECTION.

Persons Killed
Person 1: adult from NC, position front left in unit 2, no alcohol
           or drugs suspected

                                                                     This report generated on 4/10/2026
"""


@pytest.fixture()
def slip(tmp_path):
    p = tmp_path / "slip.txt"
    p.write_text(SLIP_TEXT)
    return fi.parse_fatal_slip(str(p))


def test_the_slip_parses_by_label_not_position(slip):
    assert slip.slip_number == "M269901001"
    assert slip.crash_id == "108000001"
    assert slip.crash_date == "4/8/2026" and slip.crash_time == "6:22:00 PM"
    assert slip.division == "10" and slip.region == "Metrolina"
    assert slip.county == "Union" and slip.municipality == "Stallings"
    assert slip.miles_from == 0.0
    assert slip.lat == 35.097566 and slip.lon == -80.67566
    assert "COLLIDED IN THE INTERSECTION" in slip.description
    assert len(slip.persons_killed) == 1
    assert "no alcohol or drugs suspected" in slip.persons_killed[0]


def test_road_names_read_like_the_checklist_writes_them():
    assert fi.clean_road("*LCL STALLINGS RD") == "Stallings Rd"
    assert fi.clean_road("*LCL GUION LN") == "Guion Ln"
    assert fi.clean_road("SR 1309") == "SR 1309"
    assert fi.clean_road("nc 581") == "NC 581"
    assert fi.clean_road("*") == "" and fi.clean_road("") == ""


def test_location_text_at_a_junction_and_at_an_offset(slip):
    assert slip.location_text() == "Maple Rd at Birch Ln"
    slip.miles_from = 0.25
    slip.toward_road = "*LCL OAK ST"
    assert slip.location_text() == \
        "Maple Rd, 0.25 miles from Birch Ln toward Oak St"


def test_the_prefill_is_slip_fact_only(slip):
    cl = fi.checklist_from_slip(slip, investigated_by="A Name, PE")
    assert cl.location == "Maple Rd at Birch Ln"
    assert cl.slip_number == "M269901001"
    assert cl.division == "10" and cl.county == "Union"
    assert cl.crash_history[0].startswith("Fatal crash 108000001 on")
    # the field-visit items start blank, every one of them
    assert not cl.signing and not cl.remarks and not cl.recommendations
    assert cl.speed_data == "N/A" and cl.ball_bank == "N/A"


def test_prefilled_text_passes_the_style_gate(slip):
    with pytest.raises(ValueError, match="dash"):
        fi.checklist_from_slip(slip,
                               crash_history=["48 crashes — mostly wet"])


def _fiche_wb(tmp_path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "M269901001_Fiche"
    ws.append(["Muni.\nCode", "On Road", "Miles", "Dir\nFrom", "From Road",
               "Toward Road", "Milepost Road", "MP", "IS?", "New MP", "MA",
               "Crash ID", "Date", "T", "C", "F", "L", "S", "Comments"])
    for r in rows:
        ws.append(r)
    p = str(tmp_path / "fiche.xlsx")
    wb.save(p)
    return p


def test_crash_history_narrows_to_the_site_by_road_stem(tmp_path):
    """TEAAS stores bare and sometimes truncated road names ("STALLING"
    for Stallings Rd on the real M260408001 pull), so the site filter
    matches by stem, both directions."""
    import datetime as dt
    at_site = [0, "MAPLE", 0, "", "BIRCH", "", "MAPLE", 1.0, "", "", "",
               100000001, dt.datetime(2024, 1, 1), 21, 1, 0, 1, "K", ""]
    truncated = [0, "MAPL", 0, "", "BIRCH", "", "MAPL", 1.0, "", "", "",
                 100000002, dt.datetime(2025, 6, 1), 30, 1, 0, 1, "O", ""]
    elsewhere = [0, "MAPLE", 0, "", "ELM", "", "MAPLE", 3.0, "", "", "",
                 100000003, dt.datetime(2024, 5, 1), 21, 1, 0, 1, "B", ""]
    p = _fiche_wb(tmp_path, [at_site, truncated, elsewhere])
    lines = fi.crash_history_lines(p, roads=["*LCL MAPLE RD",
                                             "*LCL BIRCH LN"])
    assert lines[0].startswith("2 crashes in the TEAAS pull")
    assert "1 fatal" in lines[0] and "1 PDO" in lines[0]
    assert "Rear End 1 (50%)" in lines[1]
    # no filter tallies the whole pull
    assert fi.crash_history_lines(p)[0].startswith("3 crashes")


def test_the_workbook_lands_on_the_documented_cells(tmp_path, slip):
    cl = fi.checklist_from_slip(slip, investigated_by="A Name, PE")
    cl.date, cl.time = "7/13/2026", "5:00 PM"
    cl.lane_widths = [("Maple Rd", "12'")]
    out = str(tmp_path / "fifile.xlsx")
    fi.build_field_investigation(out, cl)
    wb = openpyxl.load_workbook(out)
    ws = wb["Checklist"]
    assert ws["D5"].value == "Maple Rd at Birch Ln"        # docs/02
    assert ws["D7"].value == "M269901001"
    assert ws["D9"].value == "10" and ws["D11"].value == "Union"
    assert ws["H3"].value == "7/13/2026" and ws["J3"].value == "5:00 PM"
    assert ws["D45"].value.startswith("Fatal crash 108000001")
    assert "Maple Rd: 12'" in ws["D39"].value
    # narrative cells use Cambria 9 (docs/02)
    assert ws["D45"].font.name == "Cambria" and ws["D45"].font.size == 9
    # Photos captions at the documented 38-row spacing
    ph = wb["Photos"]
    assert ph["A35"].value == "Photo 1" and ph["A73"].value == "Photo 2"
    # Sketch carries the provided-map rule when no map was given
    assert "untouched" in wb["Sketch"]["A3"].value


def test_a_generated_workbook_never_carries_an_em_dash(tmp_path, slip):
    cl = fi.checklist_from_slip(slip)
    cl.remarks = ["Signal cabinet found open — exposed wiring"]
    with pytest.raises(ValueError, match="dash"):
        fi.build_field_investigation(str(tmp_path / "x.xlsx"), cl)
