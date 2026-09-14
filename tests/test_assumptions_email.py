"""Assumptions email generator tests (docs/05 template, style gate)."""
from datetime import date

import pytest

from safety_eval.assumptions_email import (AssumptionsData, default_filename,
                                           generate_assumptions_email,
                                           load_assumptions_yaml)

DATA = AssumptionsData(
    order_id="41000075552", project_id="04-15-39049",
    gps="35.6521, -78.3568", county="Johnston", division="4",
    study_type="Strip Analysis",
    location="SR 1003 (Buffalo Road) from SR 1716 to SR 2638",
    signal_id=None,                       # bullet omitted entirely
    countermeasure="Install a two-way center turn lane.",
    statement_of_problem="A pattern of left turn crashes has developed.",
    project_cost="$1,250,000",
    project_completion="June 30, 2021",
    completion_notes=["Completion based on provided project records."],
    teaas_date=date(2026, 5, 31), construction_months=14,
    construction_end=date(2021, 6, 30),
    target_crashes="Left turn crashes (Target-1) and rear ends (Target-2).",
    project_dev_summary="59 total crashes in the evaluated section.",
    additional_notes=["Crash 104781542 has no stored severity; resolve from the report."],
)


def _doc_text(path):
    import docx
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def test_generate_matches_template_structure(tmp_path):
    out = str(tmp_path / default_filename(DATA))
    generate_assumptions_email(DATA, out)
    text = _doc_text(out)
    for required in ("Evaluation Assumptions", "Order ID: 41000075552",
                     "County / Division: Johnston County / Division 4",
                     "Time Periods",
                     "Before Period: 6/1/2015 - 4/30/2020 (4 years, 11 months)",
                     "Construction: 5/1/2020 - 6/30/2021 (1 year, 2 months)",
                     "After Period: 7/1/2021 - 5/31/2026 (4 years, 11 months)",
                     "Target Crashes:", "Project Dev Crash Summary:",
                     "Additional Notes"):
        assert required in text, f"missing: {required}"
    assert "Signal ID" not in text        # omitted when None
    assert default_filename(DATA) == \
        "Assumptions Email - 41000075552 (04-15-39049).docx"


def test_style_gate_rejects_em_dash(tmp_path):
    bad = AssumptionsData(order_id="1", project_id="2",
                          countermeasure="AWSC — conversion")
    with pytest.raises(ValueError):
        generate_assumptions_email(bad, str(tmp_path / "x.docx"))


def test_yaml_loader(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("order_id: '41000075552'\nproject_id: 04-15-39049\n"
                 "signal_id: n/a\nteaas_date: 2026-05-31\n"
                 "construction_months: 14\nconstruction_end: 2021-06-30\n")
    d = load_assumptions_yaml(str(p))
    assert d.signal_id == "n/a"
    assert d.construction_months == 14
    assert d.teaas_date == date(2026, 5, 31)
