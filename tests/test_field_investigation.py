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


# --------------------------------------------------------------------------- #
# a section site: the tally narrows by milepost, and the TEAAS report's
# Summary Statistics join the Crash History block
# --------------------------------------------------------------------------- #
def _fiche_workbook(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "260399999EA_Fiche"
    ws.append(["Muni.\nCode", "On Road", "Miles", "Dir\nFrom", "From Road",
               "Toward Road", "Milepost Road", "MP", "IS?", "New MP", "MA",
               "Crash ID", "Date", "T", "C", "F", "L", "S", "Type"])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def test_a_section_site_tallies_by_milepost_on_the_route(tmp_path):
    from datetime import date
    rows = [
        [0, "US 311", 0.5, "S", "SR 1979", "SR 4543", "US 311", 10.504, "IS",
         None, None, 107699011, date(2024, 4, 20), 19, 1, 0, 5, "O", "FO"],
        [0, "US 311", 1.4, "N", "SR 1980", "SR 1979", "US 311", 11.110, "IS",
         None, None, 108571088, date(2026, 3, 7), 27, 1, 0, 3, "K", "head-on"],
        # mileposted beyond the study limits: not this site
        [0, "US 311", 0.3, "N", "SR 1948", "SR 1953", "US 311", 11.548, "NIS",
         None, None, 107209043, date(2023, 1, 9), 23, 1, 0, 1, "B", "LTSR"],
        # inside the range but on another route: not this site
        [0, "SR 1940", 0.1, "W", "US 311", "SR 1947", "SR 1940", 10.9, "NIS",
         None, None, 108397584, date(2026, 2, 6), 19, 1, 0, 1, "C", "FO"],
    ]
    wb = _fiche_workbook(tmp_path / "f.xlsx", rows)
    lines = fi.crash_history_lines(wb, roads=[], route="US 311",
                                   mp_range=(10.438, 11.2))
    assert lines[0].startswith("2 crashes in the TEAAS pull")
    assert "1 fatal" in lines[0] and "1 PDO" in lines[0]
    assert "4/20/2024 to 3/7/2026" in lines[0]
    # the road-name narrowing still works on its own
    by_road = fi.crash_history_lines(wb, roads=["US 311", "SR 1980"])
    assert by_road[0].startswith("1 crashes in the TEAAS pull")


SUMMARY_CSV = '''"North Carolina Department of Transportation
Traffic Engineering Accident Analysis System
Strip Analysis Report"
"Study Criteria Summary"
"County:","FORSYTH","City:","All and Rural"
"Date:","8/1/2021","to","7/31/2026","Study:","260399999EA"
"Location:","US 311 from A [MP 10.483] to B [MP 11.104]"
"Summary Statistics"
"High Level Crash Summary"
"Crash Type","Number of
Crashes","Percent
of Total"
"Total Crashes","19","100.00"
"Fatal Crashes","1","5.26"
"Non-Fatal Injury Crashes","7","36.84"
"Total Injury Crashes","8","42.11"
"Property Damage Only Crashes","11","57.89"
"Night Crashes","9","47.37"
"Wet Crashes","8","42.11"
"Alcohol/Drugs Involvement Crashes","1","5.26"
"Vehicle Exposure Statistics"
"Annual ADT =","4400",""
"Total Length =","1.166 (Miles)","1.876 (Kilometers)"
"Total Vehicle Exposure =","9.37 (MVMT)","15.08 (MVKMT)"
"Total Crash Rate","202.82","126.02"
"Fatal Crash Rate","10.67","6.63"
"Night Crash Rate","96.07","59.70"
"Wet Crash Rate","85.40","53.06"
"Miscellaneous Statistics"
"Severity Index =","7.72"
"EPDO Crash Index =","146.60"
"Estimated Property Damage Total = $","152100.00"
"Accident Type Summary"
"Accident Type","Number of
Crashes","Percent
of Total"
"ANIMAL","3","15.79"
"FIXED OBJECT","8","42.11"
"HEAD ON","1","5.26"
"REAR END, SLOW OR STOP","2","10.53"
"Injury Summary"
"Injury Type","Number of
Injuries","Percent
of Total"
"Fatal Injuries","1","7.14"
'''


def test_the_teaas_summary_is_read_by_label(tmp_path):
    p = tmp_path / "InitialStudy.csv"
    p.write_text(SUMMARY_CSV)
    s = fi.strip_summary(str(p))
    assert s["total"] == "19" and s["fatal"] == "1" and s["adt"] == "4400"
    assert s["rate"] == "202.82" and s["severity_index"] == "7.72"
    assert s["study"] == "260399999EA"
    assert s["period"] == "8/1/2021 to 7/31/2026"
    lines = fi.strip_summary_lines(str(p))
    assert lines[0] == ("TEAAS analysis 260399999EA, 8/1/2021 to 7/31/2026: "
                        "19 crashes, 1 fatal, 7 non-fatal injury, 11 PDO; "
                        "9 at night, 8 wet, 1 with alcohol or drugs")
    assert lines[1] == ("ADT 4,400; 1.166 miles; 9.37 (MVMT); crash rate "
                        "202.82 (fatal 10.67, night 96.07, wet 85.40); "
                        "severity index 7.72; EPDO index 146.60")
    assert s["types"] == {"ANIMAL": 3, "FIXED OBJECT": 8, "HEAD ON": 1,
                          "REAR END, SLOW OR STOP": 2}
    assert lines[2] == ("Leading types: fixed object 8 (57%), animal 3 "
                        "(21%), rear end, slow or stop 2 (14%), head on 1 "
                        "(7%)")


# --------------------------------------------------------------------------- #
# a rural section slip: the offset carries a direction letter and the
# location line says how far from town the site is (260307016EA layout;
# the facts here are synthetic)
# --------------------------------------------------------------------------- #
SECTION_SLIP_TEXT = """\
                             NCDOT Fatal Crash Notification

     Internal ID/Fatal Slip Number: 269999999EA                  Crash Date: 3/1/2026
                            Crash ID: 108000002                  Crash Time: 6:03:00 AM
Crashweb Link for Report Image:
       https://crashweb.ncdot.gov/crashweb/submitCrashIDFromTRCS.do?crashID=108000002

Location
Division 9 | Triad Region
Forsyth County, 2 miles N of Walkertown
On US 311, 1.4 miles N from SR 1980 toward SR 1979
https://www.google.com/maps/place/36.22298+-80.16971

Description
VEHICLE 1 WAS TRAVELING NORTH ON US-311. VEHICLE 2 WAS TRAVELING SOUTH.

Persons Killed
Person 1: adult from NC, position front left in unit 2, no alcohol
           or drugs suspected

                                                                     This report generated on 3/3/2026
"""


def test_a_rural_section_slip_keeps_the_offset_direction(tmp_path):
    p = tmp_path / "section_slip.txt"
    p.write_text(SECTION_SLIP_TEXT)
    slip = fi.parse_fatal_slip(str(p))
    assert slip.county == "Forsyth" and slip.municipality == ""
    assert slip.near == "2 miles N of Walkertown"
    assert slip.on_road == "US 311" and slip.from_road == "SR 1980"
    assert slip.toward_road == "SR 1979"
    assert slip.miles_from == 1.4 and slip.dir_from == "N"
    assert slip.location_text() == "US 311, 1.4 miles N from SR 1980 toward SR 1979"
    assert slip.lat == 36.22298 and slip.lon == -80.16971
