"""Results-sheet population tests, verified against the SS-6002AD completed
sheet's cell addresses (D6 Order ID ... H34:J38 Additional Information,
C58 Items for Discussion) and the docs/05 style rules."""
import os

import pytest

from safety_eval.results_sheet import (AdditionalInfoRow, ResultsData,
                                       build_results_edits, check_style,
                                       load_results_yaml,
                                       populate_results_sheet)
from safety_eval.xlsx_patch import verify_integrity

HERE = os.path.dirname(__file__)
TEMPLATE = os.path.join(
    HERE, "..", "templates", "Intersection Evaluation Workbook - 2023-12-04.xlsx")

needs_template = pytest.mark.skipif(
    not os.path.exists(TEMPLATE), reason="template not present")

DATA = ResultsData(
    order_id="41000078044 (1 of 2)",
    project_id="02-20-62356 (SS-6002AD)",
    signal_id="n/a",
    location="NC 91 at SR 1225 (Speights Bridge Road)/SR 1303 (Fieldsboro Road)",
    gps="35.584352, -77.699274",
    county="Greene",
    city="n/a",
    division="2",
    countermeasures="Convert intersection to All-Way STOP Control (AWSC).",
    cost="$22,000 (both locations)",
    completion_date="March 29, 2022",
    analysis_criteria="Treatment data consists of all crashes at the intersection.",
    target_crashes="Frontal impact crashes (LTSR, LTDR, RTSR, RTDR, head-on, angle).",
    additional_info=[
        AdditionalInfoRow("Target Crashes: EB SR 1225 At-Fault", 5, 0),
        AdditionalInfoRow("Target Crashes: Ran Stop Sign", 0, 1),
    ],
    items_for_discussion=[
        "The single after-period target crash involved a NB pickup.",
        "Class A injuries were eliminated in the after period.",
    ],
)


# --- style gate ------------------------------------------------------------
def test_check_style_rejects_em_dash():
    with pytest.raises(ValueError):
        check_style("frequency rose — severity fell", "test")


def test_build_rejects_em_dash_in_text():
    bad = ResultsData(countermeasures="AWSC — full conversion")
    with pytest.raises(ValueError):
        build_results_edits(TEMPLATE, bad)


# --- cell addressing (ground truth: completed SS-6002AD) --------------------
@needs_template
def test_identity_block_addresses():
    """Label-driven addressing against the PRISTINE 2023-12-04 template
    (its label rows differ from the completed SS-6002AD workbook; the value
    cell is always one column right of its label)."""
    edits = {e.ref: e.value for e in build_results_edits(TEMPLATE, DATA)}
    assert edits["D6"] == DATA.order_id        # 'Order ID:' at C6
    assert edits["D7"] == DATA.project_id
    assert edits["D9"] == DATA.location
    assert edits["D13"] == DATA.gps            # 'GPS Coordinates:' at C13
    assert edits["D14"] == "Greene"
    assert edits["D18"] == DATA.countermeasures
    assert edits["D23"] == DATA.cost
    assert edits["D24"] == DATA.completion_date
    assert edits["D31"] == DATA.analysis_criteria   # 'Analysis Criteria:' at C31
    assert edits["D36"] == DATA.target_crashes


@needs_template
def test_additional_info_rows_and_na_fill():
    edits = {e.ref: e.value for e in build_results_edits(TEMPLATE, DATA)}
    assert edits["H34"] == "Target Crashes: EB SR 1225 At-Fault"
    assert edits["I34"] == 5 and edits["J34"] == 0
    assert edits["H35"] == "Target Crashes: Ran Stop Sign"
    # remaining rows keep n/a in the leftmost column, counts cleared
    assert edits["H36"] == "n/a"
    assert edits["I36"] is None


@needs_template
def test_items_for_discussion_bulleted_block():
    edits = {e.ref: e.value for e in build_results_edits(TEMPLATE, DATA)}
    block = edits["C58"]
    assert block.startswith("• ")
    assert block.count("\n") == 1
    assert "NB pickup" in block and "Class A" in block


@needs_template
def test_populate_and_integrity(tmp_path):
    out = str(tmp_path / "results.xlsx")
    populate_results_sheet(TEMPLATE, out, DATA)
    report = verify_integrity(TEMPLATE, out)
    assert report.ok, report.problems

    import openpyxl
    ws = openpyxl.load_workbook(out)["1 page results - 1 Target"]
    assert ws["D6"].value == DATA.order_id
    assert "AWSC" in ws["D18"].value
    assert ws["C58"].value.startswith("• ")


# --- yaml loader -----------------------------------------------------------
def test_load_results_yaml(tmp_path):
    p = tmp_path / "results.yaml"
    p.write_text(
        "order_id: '41000078044'\n"
        "county: Greene\n"
        "division: 2\n"
        "additional_info:\n"
        "  - {label: 'TC: Ran Stop Sign', before: 0, after: 1}\n"
        "items_for_discussion:\n"
        "  - First point.\n")
    d = load_results_yaml(str(p))
    assert d.order_id == "41000078044"
    assert d.division == "2"
    assert d.additional_info[0].after == 1
    assert d.items_for_discussion == ["First point."]
