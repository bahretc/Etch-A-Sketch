"""Field-geometry redaction: cover PII by WHERE it is, keep the crash facts.

Synthetic word boxes only; no real report content.
"""
from safety_eval.form_geometry import (DMV349_FRONT, Zone, harvest_names,
                                       is_front_page, location_vocabulary,
                                       register, scrub_targets, zone_rects)
from safety_eval.redact import Word

W, H = 1000, 2000


def _w(text, xf, yf, page=1):
    return Word(text=text, left=int(xf * W), top=int(yf * H),
                width=max(8, 9 * len(text)), height=14, page=page)


def test_front_page_detected_by_header_markers():
    assert is_front_page([_w("DMV-349", .05, .01), _w("Units", .1, .04),
                          _w("Involved", .15, .04)])
    assert not is_front_page([_w("DIAGRAM", .05, .3), _w("NARRATIVE", .05, .6)])


def test_register_identity_when_anchors_missing():
    assert register([_w("nothing", .1, .5)], H) == (1.0, 0.0)


def test_register_fits_shifted_scan():
    # anchors printed 2% lower than nominal
    words = [_w("LOCATION", .02, .155 + .02), _w("Owner", .05, .445 + .02),
             _w("Names", .40, .735 + .02), _w("Injured", .05, .965 + .02)]
    scale, offset = register(words, H)
    assert abs(scale - 1.0) < 0.05 and abs(offset - 0.02) < 0.01


def test_zones_cover_identity_and_spare_the_location_band():
    rects = zone_rects(W, H, (1.0, 0.0))
    tops = [r[1] for _z, r in rects]
    assert min(tops) > 0.22 * H          # nothing reaches the location block
    names = {z.name for z, _r in rects}
    assert {"driver-identity", "owner-identity", "persons-table"} <= names


def test_harvest_collects_names_not_captions():
    words = [_w("Driver", .05, .25), _w("MERIWETHER", .20, .25),
             _w("Address", .05, .29), _w("City", .05, .31)]
    got = harvest_names(words, W, H, (1.0, 0.0))
    assert "MERIWETHER" in got
    assert "DRIVER" not in got and "ADDRESS" not in got


def test_location_vocabulary_protects_place_names():
    words = [_w("GREENE", .30, .05), _w("SNOW", .25, .16), _w("HILL", .30, .16),
             _w("MERIWETHER", .20, .25)]
    protected = location_vocabulary(words, H)
    assert {"GREENE", "SNOW", "HILL"} <= protected
    assert "MERIWETHER" not in protected     # identity zone is below the band


def test_scrub_targets_finds_names_in_narrative():
    narrative = [_w("VEHICLE", .05, .60), _w("1", .12, .60),
                 _w("DRIVEN", .15, .60), _w("BY", .22, .60),
                 _w("MERIWETHER,", .26, .60), _w("EAST", .40, .60)]
    hits = scrub_targets(narrative, {"MERIWETHER"})
    assert [w.text for w in hits] == ["MERIWETHER,"]   # trailing comma handled


def test_scrub_leaves_the_account_intact():
    narrative = [_w("TRAVELING", .05, .60), _w("EAST", .15, .60),
                 _w("ON", .20, .60), _w("US", .24, .60), _w("13", .28, .60)]
    assert scrub_targets(narrative, {"MERIWETHER"}) == []
