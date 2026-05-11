from bot.digest_bot import (
    MAX_DIGEST_HOURS,
    MAX_TG_MSG,
    _split_for_telegram,
    parse_period,
)


def test_parse_period_bare_number_is_hours():
    assert parse_period("6") == 6
    assert parse_period("24") == 24


def test_parse_period_hour_suffix():
    assert parse_period("1h") == 1
    assert parse_period("48h") == 48
    assert parse_period("12H") == 12


def test_parse_period_day_suffix():
    assert parse_period("1d") == 24
    assert parse_period("7d") == 168
    assert parse_period("2D") == 48


def test_parse_period_russian_suffix():
    assert parse_period("6ч") == 6
    assert parse_period("3д") == 72


def test_parse_period_rejects_invalid():
    assert parse_period("abc") is None
    assert parse_period("") is None
    assert parse_period("h") is None


def test_parse_period_rejects_out_of_range():
    assert parse_period("0") is None
    assert parse_period("0h") is None
    assert parse_period("200h") is None
    assert parse_period("10d") is None


def test_parse_period_handles_whitespace():
    assert parse_period(" 6h ") == 6


def test_split_for_telegram_short():
    assert _split_for_telegram("short") == ["short"]


def test_split_for_telegram_long_respects_limit():
    text = "line\n" * 2000
    chunks = _split_for_telegram(text)
    assert all(len(c) <= MAX_TG_MSG for c in chunks)


def test_split_for_telegram_preserves_lines():
    text = "abc\n" * 1500
    chunks = _split_for_telegram(text)
    merged = "\n".join(chunks)
    assert merged.count("abc") == text.count("abc")


def test_max_digest_hours_is_week():
    assert MAX_DIGEST_HOURS == 168
