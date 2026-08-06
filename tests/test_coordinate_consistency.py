"""Pairwise fiche-coordinate consistency (docs/11).

Pins the arithmetic on constructed rows where the right answer is known, and
pins the real I-40 sample the docs/11 table reports so the numbers there cannot
drift away from the code that produced them.
"""
import pytest

from safety_eval.location import coordinate_consistency, in_nc


def _buckets(result):
    """The source buckets, without the "_dropped" bookkeeping key."""
    return {k: v for k, v in result.items() if k != "_dropped"}

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
    assert _buckets(coordinate_consistency(rows, max_dmp=1.5)) == {}


def test_unmileposted_rows_are_dropped():
    """MP 999.999 means the crash was never mileposted (docs/09)."""
    rows = [(999.999, 35.0, -80.0, "DMV349"), (10.0, 35.0, -80.0, "DMV349")]
    assert _buckets(coordinate_consistency(rows)) == {}


def test_rows_missing_a_coordinate_are_dropped():
    rows = [(10.0, None, None, ""), (10.1, 35.0, -80.0, "DMV349")]
    assert _buckets(coordinate_consistency(rows)) == {}


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
# guards the full-population run exposed
# ---------------------------------------------------------------------------

#: The median remilepost the engineer actually made on 04-15-39049. A method
#: whose own noise exceeds this cannot find the correction it is looking for.
REAL_REMILEPOST_FT = 634


def test_out_of_state_coordinates_are_dropped_and_counted():
    """5.4% of raw DMV349 coordinates were outside NC entirely (docs/11).

    The observed corruptions are a longitude carrying the latitude's value and
    a longitude with its sign dropped. Silently averaging them in produced a
    2,600 mile "disagreement"; they must be excluded AND surfaced.
    """
    rows = [(10.0, 35.0, -80.0, "DMV349"),
            (10.1, 35.0 + DEG, -80.0, "DMV349"),
            (10.2, 35.59271, -35.58545, "DMV349"),     # lon holds the lat value
            (10.3, 35.59195, 82.42702, "DMV349")]      # lon sign dropped
    out = coordinate_consistency(rows)
    assert out["_dropped"] == 2
    assert out["report"]["n"] == 1                      # only the clean pair


def test_in_nc_rejects_the_observed_corruptions():
    assert in_nc(35.59271, -82.05715)
    assert not in_nc(35.59271, -35.58545)               # lon = lat value
    assert not in_nc(35.59195, 82.42702)                # sign dropped
    assert not in_nc(82.68692, -35.55438)               # both wrong


def test_pooling_two_counties_is_the_documented_hazard():
    """NCDOT mileposts restart at county lines.

    "I 40 MP 15" exists in Buncombe and in McDowell about 40 miles apart. Two
    such crashes look adjacent by milepost and are nowhere near each other, so
    the caller must pass one route in one county. This pins how badly it goes
    if they don't, so the docstring's warning stays honest.
    """
    buncombe = (15.0, 35.5570, -82.5990, "DMV349")
    mcdowell = (15.0, 35.6380, -82.0149, "DMV349")
    out = coordinate_consistency([buncombe, mcdowell])
    assert out["report"]["median_ft"] > 150_000          # ~34 miles of nonsense


def test_a_realistic_freeway_spread_does_not_beat_a_remilepost():
    """Crashes sharing one coded interchange milepost really are spread out.

    This is why the gap is an upper bound on coordinate error rather than a
    measurement of it, and why the conclusion holds anyway: whatever produces
    the spread, a 634 ft correction cannot be seen through it.
    """
    rows = [(8.200, 35.558625, -82.631611, "DMV349CLEANED"),
            (8.200, 35.557138, -82.608812, "DMV349CLEANED")]
    assert coordinate_consistency(rows)["report"]["median_ft"] > REAL_REMILEPOST_FT
