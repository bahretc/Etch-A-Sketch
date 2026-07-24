"""Assignment email parser tests. The body fixture mirrors the real
SS-6002M/SS-6002AS thread structure (bullet labels, tab-indented sub-bullets,
flattened Time Periods table, safelinks-wrapped URLs, quoted older copies of
the same blocks, and a signature after the last block)."""
from datetime import date

from safety_eval.assignment_email import (clean_text, parse_assignment_email,
                                          parse_block, split_assignments,
                                          to_assignment_dict,
                                          to_assumptions_dict)

BODY = """Hello,

Below are assumptions for Assignment #22 and #23.

Assignment #22

*\tOrder ID: 41000075552
*\tProject ID: 02-20-61721 (TIP #SS-6002M)
*\tLocation: US 13 between the Wayne County Line and NC 58 (MP 0.00 to MP 7.38; 7.38 miles)

\t*\tUS 13 between NC 91 and the Pitt County Line (MP 9.736 to MP 18.381; 8.65 miles)

*\tGPS Coordinates: 35.441163, -77.824727 <https://www.google.com/maps?q=35.441163,-77.824727>  to 35.459322, -77.704184 <https://www.google.com/maps?q=35.459322,-77.704184>
*\tCounty/Division: Greene County / Division 2
*\tCountermeasure: Install the following,

\t*\tSinusoidal centerline rumble strips (18-inch width)
\t*\tSinusoidal edgeline rumble strips (8-inch width)

*\tTotal Cost Estimate: $116,000
*\tProject Completion: 10/16/2021 (construction began 5/26/2021)
*\tTime Periods:

Period

Start

End

Duration

Before

11/1/2016

4/30/2021

4 years 6 months

Construction

5/1/2021

10/31/2021

6 months

After

11/1/2021

4/30/2026

4 years 6 months

*\tTarget Crashes:

\t*\tLane Departure crashes (Type 1).
\t*\tThe Additional Information table will include Correctable Lane Departure breakdowns.

*\tProject Development Crash Summary: 155 total crashes (3K, 4A, 11B, 37C, 100PDO) from 7/1/2015 to 6/30/2020
*\tAdditional Notes/Questions:

\t*\tShould the evaluation include the added section? Yes, please include it.

Assignment #23

*\tOrder ID: 41000078043
*\tProject ID: 02-20-62355 (TIP #SS-6002AS)
*\tLocation: US 13 at SR 1132 (Shine Road/Free Gospel Road)
*\tGPS Coordinates: 35.440469, -77.791892 <https://www.google.com/maps?q=35.440469,-77.791892>
*\tCounty/Division: Greene County/Division 2
*\tSignal ID: 02-0240
*\tCountermeasure: Revise the existing static flashers to a VEWF system on US 13
*\tTotal Cost Estimate: $65,000
*\tProject Completion: 2/3/2022 (construction began 12/15/2021)
*\tTime Periods:

Before

3/1/2017

4/30/2021

Construction

5/1/2021

2/28/2022

After

3/1/2022

4/30/2026

*\tTarget Crashes: Frontal impact crashes involving Vehicles from US 13 and SR 1132

Best regards,

Chris Bahret, PE
P  919.439.2833 <tel:919.439.2833>

From: Klemann, Kendra R
Sent: Thursday, June 11, 2026 10:12 AM
Subject: RE: [External] Safety Evaluation

Assignment #22

*\tOrder ID: STALE-OLD-COPY
"""


def test_clean_text_strips_link_wrappers_keeps_visible_text():
    out = clean_text("35.44, -77.82 <https://x.example/maps?q=1> end "
                     "<mailto:a@b.c> ")
    assert "https://" not in out and "mailto" not in out
    assert "35.44, -77.82" in out


def test_split_keeps_newest_copy_and_cuts_at_signature():
    blocks = split_assignments(BODY)
    assert set(blocks) == {"22", "23"}
    assert "STALE-OLD-COPY" not in blocks["22"]      # quoted copy ignored
    assert "Chris Bahret" not in blocks["23"]        # signature cut
    assert "919.439" not in blocks["23"]


def test_parse_section_assignment():
    pa = parse_block("22", split_assignments(BODY)["22"])
    assert pa.order_id == "41000075552"
    assert pa.project_id == "02-20-61721"
    assert pa.tip == "SS-6002M"
    assert pa.county == "Greene" and pa.division == "2"
    assert pa.signal_id is None
    assert not pa.intersection_study
    assert pa.gps == [(35.441163, -77.824727), (35.459322, -77.704184)]
    assert pa.location_notes and "MP 9.736" in pa.location_notes[0]
    assert pa.cost == "$116,000"
    assert pa.completion == "10/16/2021"
    assert pa.construction_began == "5/26/2021"
    assert pa.periods == {
        "before": (date(2016, 11, 1), date(2021, 4, 30)),
        "construction": (date(2021, 5, 1), date(2021, 10, 31)),
        "after": (date(2021, 11, 1), date(2026, 4, 30)),
    }
    # caption-only Target Crashes: first sub-bullet promoted to the value
    assert pa.target_crashes == "Lane Departure crashes (Type 1)."
    assert len(pa.target_notes) == 1
    assert "155 total crashes" in pa.dev_summary
    assert pa.notes == ["Should the evaluation include the added section? "
                        "Yes, please include it."]
    # 'the following,' countermeasure folds its sub-bullets in
    cm = pa.countermeasure_text()
    assert cm.startswith("Install the following:")
    assert "centerline rumble strips" in cm and cm.endswith(".")


def test_parse_intersection_assignment():
    pa = parse_block("23", split_assignments(BODY)["23"])
    assert pa.signal_id == "02-0240"
    assert pa.intersection_study
    assert pa.gps == [(35.440469, -77.791892)]
    assert pa.county == "Greene" and pa.division == "2"
    assert pa.periods["construction"] == (date(2021, 5, 1), date(2022, 2, 28))
    assert pa.target_crashes.startswith("Frontal impact")


def test_conversions_feed_existing_loaders(tmp_path):
    import yaml

    from safety_eval.assumptions_email import load_assumptions_yaml

    pa = parse_block("23", split_assignments(BODY)["23"])
    d = to_assumptions_dict(pa)
    path = str(tmp_path / "a.yaml")
    with open(path, "w") as fh:
        yaml.safe_dump(d, fh)
    data = load_assumptions_yaml(path)
    assert data.order_id == "41000078043"
    assert data.signal_id == "02-0240"
    assert data.construction_months == 10       # 5/2021 - 2/2022 inclusive
    assert str(data.construction_end) == "2022-02-28"
    assert data.study_type == "Intersection Analysis"

    a22 = to_assignment_dict(parse_block("22", split_assignments(BODY)["22"]))
    assert a22["section_begin_mp"] == 0.0
    assert a22["section_end_mp"] == 7.38
    assert a22["study_start"] == "2016-11-01"
    assert a22["study_end"] == "2026-04-30"
    assert a22["construction_start"] == "2021-05-01"
    assert not a22["intersection_study"]


def test_eml_end_to_end(tmp_path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "RE: Safety Evaluation - Assignment #22 & 23"
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg.set_content(BODY)
    path = str(tmp_path / "assignment.eml")
    with open(path, "wb") as fh:
        fh.write(bytes(msg))

    parsed = parse_assignment_email(path)
    assert set(parsed) == {"22", "23"}
    assert parsed["22"].tip == "SS-6002M"
    assert parsed["23"].periods["after"] == (date(2022, 3, 1),
                                             date(2026, 4, 30))
