"""The study types and the analyses each one offers (intersection, section,
bike/ped intersection), the one place the app branches on them."""
import pytest

from safety_eval import study_type as t


def test_each_study_type_offers_its_analyses_in_order():
    assert t.analyses_for("fatal") == ("section", "intersection")
    assert t.analyses_for("hsip") == ("section", "intersection", "bikeped")
    assert t.analyses_for("evaluation") == ("intersection", "section")
    assert t.default_analysis("hsip") == "section"
    assert t.default_analysis("evaluation") == "intersection"
    assert [lab for _, lab in t.analysis_choices("hsip")] == [
        "Section", "Intersection", "Bike/Ped Intersection"]


def test_bike_ped_is_an_hsip_package_shape_only():
    assert t.check_analysis("hsip", "bikeped") == "bikeped"
    for other in ("fatal", "evaluation"):
        with pytest.raises(ValueError, match="not Bike/Ped"):
            t.check_analysis(other, "bikeped")
    assert t.check_analysis("evaluation", "Section") == "section"


def test_older_vocabularies_resolve_to_the_same_kinds():
    """The package maps say ``strip``, the diagram layouts say ``bikeped``
    and the warrants radio said ``Section (strip)``; all one vocabulary."""
    assert t.get_analysis("strip").key == "section"
    assert t.get_analysis("Section (strip)").key == "section"
    assert t.get_analysis("junction").key == "intersection"
    assert t.get_analysis("Bike/Ped (aerial)").key == "bikeped"
    assert t.get_analysis(t.ANALYSIS_KINDS["bikeped"]).key == "bikeped"
    with pytest.raises(ValueError, match="unknown analysis"):
        t.get_analysis("roundabout")


def test_the_facts_that_hang_off_an_analysis():
    """docs/12: bike/ped is always a 10-year intersection pull with a 300 ft
    y-line; a section is the package maps' strip site."""
    bp = t.get_analysis("bikeped")
    assert (bp.years, bp.yline_ft, bp.site) == (10, 300, "intersection")
    assert bp.is_intersection
    assert t.get_analysis("intersection").yline_ft == 150
    sec = t.get_analysis("section")
    assert sec.site == "strip" and sec.yline_ft is None
    assert not sec.is_intersection
    assert t.STUDY_TYPES["hsip"].default_analysis == "section"
