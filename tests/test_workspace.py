"""The per-study workspace: attach once, read by role, never delete."""
import json
import os

import pytest

from safety_eval import workspace as wsm


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    return str(tmp_path / "studies")


def test_create_open_and_list(base):
    ws = wsm.Workspace.create("41000079305", study_type="hsip")
    assert ws.study == "41000079305" and ws.study_type == "hsip"
    assert os.path.isdir(os.path.join(ws.root, "inputs"))
    again = wsm.Workspace.open("41000079305")
    assert again.manifest["created"] == ws.manifest["created"]
    assert wsm.list_studies() == ["41000079305"]


def test_creating_the_same_study_twice_refuses(base):
    wsm.Workspace.create("41000079305")
    with pytest.raises(ValueError, match="already exists"):
        wsm.Workspace.create("41000079305")


def test_study_names_cannot_escape_the_base(base):
    for bad in ("../evil", "a/b", "", " ", ".hidden"):
        with pytest.raises(ValueError):
            wsm.Workspace.create(bad)


def test_single_roles_replace_and_multi_roles_accumulate(base):
    ws = wsm.Workspace.create("s1")
    ws.attach("fiche_csv", "one.csv", b"a")
    ws.attach("fiche_csv", "two.csv", b"b")
    assert os.path.basename(ws.path("fiche_csv")) == "two.csv"
    assert len(ws.paths("fiche_csv")) == 1
    ws.attach("features_report", "US74.pdf", b"f1")
    ws.attach("features_report", "NC218.pdf", b"f2")
    assert [os.path.basename(p) for p in ws.paths("features_report")] == \
        ["US74.pdf", "NC218.pdf"]


def test_unknown_roles_are_refused(base):
    ws = wsm.Workspace.create("s1")
    with pytest.raises(ValueError, match="unknown role"):
        ws.attach("mystery", "x.bin", b"?")


def test_adopt_output_copies_from_outside_and_records_in_place(base, tmp_path):
    ws = wsm.Workspace.create("s1")
    outside = tmp_path / "built.xlsx"
    outside.write_bytes(b"wb")
    p = ws.adopt_output("workbook", str(outside))
    assert p.startswith(os.path.abspath(ws.root))
    assert ws.path("workbook") == p
    inside = os.path.join(ws.outputs_dir, "reviewed.xlsx")
    with open(inside, "wb") as fh:
        fh.write(b"r")
    q = ws.adopt_output("reviewed_workbook", inside)
    assert os.path.samefile(q, inside)  # recorded in place, not duplicated


def test_params_merge_and_none_means_no_change(base):
    ws = wsm.Workspace.create("s1")
    ws.set_params(route="US 74", mp_lo=13.56, mp_hi=13.815)
    ws.set_params(route=None, context="rural")
    again = wsm.Workspace.open("s1")
    assert again.param("route") == "US 74"
    assert again.param("context") == "rural"
    assert again.param("missing", 5) == 5


def test_missing_attached_files_are_dropped_from_paths(base):
    ws = wsm.Workspace.create("s1")
    p = ws.attach("binder_index", "idx.json", b"{}")
    os.remove(p)
    assert ws.path("binder_index") is None


def test_manifest_is_plain_readable_json(base):
    ws = wsm.Workspace.create("s1", study_type="evaluation")
    ws.attach("setup_yaml", "setup.yaml", b"x: 1")
    data = json.load(open(os.path.join(ws.root, "manifest.json")))
    assert data["study_type"] == "evaluation"
    assert data["files"]["setup_yaml"] == [os.path.join("inputs",
                                                        "setup.yaml")]


# --------------------------------------------------------------------------- #
# the study's analysis (intersection, section, bike/ped intersection)
# --------------------------------------------------------------------------- #
def test_a_new_study_records_its_analysis_defaulting_per_type(base):
    hs = wsm.Workspace.create("41000079305", study_type="hsip")
    assert hs.analysis == "section" and hs.has_analysis
    ev = wsm.Workspace.create("41000076575", study_type="evaluation")
    assert ev.analysis == "intersection"
    data = json.load(open(os.path.join(ev.root, "manifest.json")))
    assert data["analysis"] == "intersection"
    bp = wsm.Workspace.create("59X00239", study_type="hsip",
                              analysis="bikeped")
    assert wsm.Workspace.open("59X00239").analysis == "bikeped"


def test_an_analysis_the_type_does_not_offer_is_refused(base):
    with pytest.raises(ValueError, match="not Bike/Ped"):
        wsm.Workspace.create("s1", study_type="evaluation",
                             analysis="bikeped")
    assert wsm.list_studies() == []          # nothing half-made
    ws = wsm.Workspace.create("s1", study_type="fatal")
    with pytest.raises(ValueError):
        ws.set_analysis("bikeped")
    assert ws.set_analysis("intersection") == "intersection"
    assert wsm.Workspace.open("s1").analysis == "intersection"


def test_a_study_from_before_the_field_answers_from_its_site(base):
    """Older manifests carry no analysis: the package-maps ``site`` param
    stands in (``strip`` is a section), else the type's default, and the
    choice stays open until recorded."""
    ws = wsm.Workspace.create("260307016EA", study_type="fatal")
    del ws.manifest["analysis"]
    ws.save()
    old = wsm.Workspace.open("260307016EA")
    assert old.analysis == "section" and not old.has_analysis
    old.set_params(site="intersection")
    assert wsm.Workspace.open("260307016EA").analysis == "intersection"
    old.set_params(site="strip")
    assert wsm.Workspace.open("260307016EA").analysis == "section"
    old.set_analysis("intersection")
    again = wsm.Workspace.open("260307016EA")
    assert again.analysis == "intersection" and again.has_analysis
