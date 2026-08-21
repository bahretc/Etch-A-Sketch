"""The TEAAS data-currency line, as it appears on the NCDOT Connect
page: month and year separated by a non-breaking space entity."""
from safety_eval.teaas_currency import parse_currency


def test_parses_the_nbsp_entity_form():
    html = ('<span style="color:red">TEAAS crash data is now available '
            'through July&#160;2026.</span>')
    assert parse_currency(html) == "July 2026"


def test_parses_a_literal_non_breaking_space():
    assert parse_currency("available through July 2026") == "July 2026"


def test_parses_a_plain_space_and_any_case():
    text = "TEAAS crash data is now Available Through SEPTEMBER 2027."
    assert parse_currency(text) == "September 2027"


def test_line_broken_across_whitespace_still_parses():
    assert parse_currency("available through\n March 2026") == "March 2026"


def test_absent_line_returns_none():
    assert parse_currency("<html><body>maintenance page</body></html>") is None


def test_a_non_month_word_does_not_match():
    assert parse_currency("available through version 2026") is None
