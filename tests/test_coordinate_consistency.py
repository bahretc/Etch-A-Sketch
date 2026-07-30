"""Pairwise fiche-coordinate consistency (docs/11).

Pins the arithmetic on constructed rows where the right answer is known, and
pins the real I-40 sample the docs/11 table reports so the numbers there cannot
drift away from the code that produced them.
"""
import pytest

from safety_eval.location import coordinate_consistency

# 1 degree of latitude is close enough to 364,000 ft for a constructed case;
# 0.01 degrees is therefore about 3,640 ft, or 0.6894 miles.
DEG = 0.01
DEG_FT = 3640.0


def test_perfectly_consistent_rows_have_a_small_gap():
    """Coordinates spaced exactly as far apart as their mileposts say."""
    rows = [(10.0, 35.0, -80.0, "DMV349"),
            (10.0 + DEG_FT / 5280.0, 35.0 + DEG, -80.0, "DMV349")]
    out = coordinate_consistency(rows)
    assert out["report"]["n"] == 1
    assert out["report"]["median_ft"] < 20        # only projection rounding


def test_a_wrong_coordinate_shows_up_as_the_gap():
    """Same milepost, moved 3,640 ft north: the gap is that whole distance."""
    rows = [(10.0, 35.0, -80.0, "DMV349"),
            (10.0, 35.0 + DEG, -80.0, "DMV349")]
    gap = coordinate_consistency(rows)["report"]["median_ft"]
    assert 3500 < gap < 3800


def test_report_and_research_sources_are_bucketed_apart():
    rows = [(10.0, 35.0, -80.0, "DMV349CLEANED"),
            (10.1, 35.0 + DEG, -80.0, "DMV349"),
            (10.2, 35.0 + 2 * DEG, -80.0, "ITRE_CMV")]
    out = coordinate_consistency(rows)
    assert out["report"]["n"] == 1               # the two DMV349 rows
    assert out["other"]["n"] == 2                # every pair touching ITRE


def test_far_apart_pairs_are_excluded():
    """Only short baselines are usable; a curve would corrupt a long one."""
    rows = [(1.0, 35.0, -80.0, "DMV349"), (9.0, 35.1, -80.0, "DMV349")]
    assert coordinate_consistency(rows, max_dmp=1.5) == {}


def test_unmileposted_rows_are_dropped():
    """MP 999.999 means the crash was never mileposted (docs/09)."""
    rows = [(999.999, 35.0, -80.0, "DMV349"), (10.0, 35.0, -80.0, "DMV349")]
    assert coordinate_consistency(rows) == {}


def test_rows_missing_a_coordinate_are_dropped():
    rows = [(10.0, None, None, ""), (10.1, 35.0, -80.0, "DMV349")]
    assert coordinate_consistency(rows) == {}


def test_median_is_the_true_median_on_an_even_count():
    """Guards the quantile: an upper-middle pick reported 990 ft for 877."""
    rows = [(10.0, 35.0, -80.0, "DMV349"),
            (10.2, 35.0 + DEG, -80.0, "DMV349"),
            (10.4, 35.0 + 2 * DEG, -80.0, "DMV349"),
            (10.6, 35.0 + 3 * DEG, -80.0, "DMV349")]
    out = coordinate_consistency(rows)["report"]
    gaps = out["gaps_ft"]
    assert out["n"] == len(gaps) and out["n"] % 2 == 0
    assert out["median_ft"] == pytest.approx(
        (gaps[out["n"] // 2 - 1] + gaps[out["n"] // 2]) / 2)


# ---------------------------------------------------------------------------
# the real sample docs/11 reports
# ---------------------------------------------------------------------------

#: I-40 rows carrying both a milepost and coordinates, transcribed from the
#: Drive preview of DetailedFicheBuncombe.csv and DetailedFicheMcDowell.csv.
#: A small, non-random sample; see docs/11 for what it does and does not show.
BUNCOMBE = [
    (1.850, 35.550084, -82.736781, "HSRC_PED"),
    (7.550, 35.559624, -82.644968, "ITRE_CMV"),
    (7.650, 35.558997, -82.636596, "ITRE_CMV"),
    (7.854, 35.558593, -82.633211, "ITRE_CMV"),
    (8.160, 35.557838, -82.626997, "ITRE_CMV"),
    (8.200, 35.558625, -82.631611, "ITRE_CMV"),
    (9.200, 35.558849, -82.635246, "ITRE_CMV"),
    (9.200, 35.557138, -82.608812, "ITRE_CMV"),
    (9.901, 35.557082, -82.599434, "ITRE_CMV"),
    (9.920, 35.557638, -82.596423, "ITRE_CMV"),
    (13.915, 35.556564, -82.513268, "ITRE_CMV"),
    (15.852, 35.556807, -82.518746, "ITRE_CMV"),
    (16.276, 35.559783, -82.502379, "ITRE_CMV"),
    (16.282, 35.565619, -82.502194, "ITRE_CMV"),
    (16.352, 35.560055, -82.502147, "ITRE_CMV"),
]
MCDOWELL = [
    (13.617, 35.643430, -82.044470, "DMV349CLEANED"),
    (13.717, 35.643980, -82.041860, "DMV349CLEANED"),
    (15.805, 35.638044, -82.014860, "DMV349CLEANED"),
    (16.023, 35.635370, -82.008430, "DMV349CLEANED"),
    (17.016, 35.635000, -81.996140, "DMV349CLEANED"),
    (17.700, 35.640662, -81.989530, "DMV349"),
    (19.981, 35.665769, -81.956540, "DMV349CLEANED"),
    (22.005, 35.683902, -81.925510, "DMV349CLEANED"),
    (25.767, 35.695890, -81.866250, "DMV349CLEANED"),
    (26.043, 35.696175, -81.866840, "DMV349CLEANED"),
]

#: The median remilepost the engineer actually made on 04-15-39049. A method
#: whose own noise exceeds this cannot find the correction it is looking for.
REAL_REMILEPOST_FT = 634


def test_reproduces_the_documented_buncombe_numbers():
    out = coordinate_consistency(BUNCOMBE)["other"]
    assert out["n"] == 28
    assert round(out["median_ft"]) == 1584
    assert round(out["max_ft"]) == 7870


def test_reproduces_the_documented_mcdowell_numbers():
    out = coordinate_consistency(MCDOWELL)["report"]
    assert out["n"] == 6
    assert round(out["median_ft"]) == 877


def test_neither_sample_beats_a_real_remilepost():
    """The finding docs/11 records: the noise is bigger than the signal."""
    for rows in (BUNCOMBE, MCDOWELL):
        for stats in coordinate_consistency(rows).values():
            assert stats["median_ft"] > REAL_REMILEPOST_FT


def test_report_sourced_coordinates_beat_research_feeds():
    """Why any use of these must filter on the Source column."""
    research = coordinate_consistency(BUNCOMBE)["other"]["median_ft"]
    report = coordinate_consistency(MCDOWELL)["report"]["median_ft"]
    assert report < research
