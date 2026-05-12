from bot.userbot.alerter import (
    DEBOUNCE_SECONDS,
    DEFAULT_KEYWORDS,
    IP_PATTERN,
    _check_alert,
    _debounce_state,
    _is_debounced,
    parse_keywords,
)


def setup_function(_func):
    _debounce_state.clear()


def test_parse_keywords_empty_returns_defaults():
    assert parse_keywords(None) == DEFAULT_KEYWORDS
    assert parse_keywords("") == DEFAULT_KEYWORDS


def test_parse_keywords_splits_comma_separated():
    out = parse_keywords("kw1, kw2 ,KW3")
    assert out == ["kw1", "kw2", "kw3"]


def test_parse_keywords_strips_whitespace():
    assert parse_keywords("  hello   ") == ["hello"]


def test_parse_keywords_skips_empty_items():
    assert parse_keywords(",,hello,,") == ["hello"]


def test_parse_keywords_all_empty_falls_back_to_defaults():
    assert parse_keywords(", , ,") == DEFAULT_KEYWORDS


def test_ip_pattern_classic():
    assert IP_PATTERN.search("выведен 1.2.3.4")


def test_ip_pattern_xxx_octet():
    assert IP_PATTERN.search("subnet 10.0.0.xxx")


def test_ip_pattern_star_octet():
    assert IP_PATTERN.search("subnet 10.0.0.*")


def test_check_alert_matches_keyword():
    matched = _check_alert(1, "Сервер критично упал", "user1", ["критично", "упал"])
    assert matched in ("критично", "упал")


def test_check_alert_no_match():
    assert _check_alert(2, "просто текст", "user1", ["foo", "bar"]) is None


def test_check_alert_ip_bonus():
    matched = _check_alert(3, "1.2.3.4 кёрнел", "user1", ["кёрнел"])
    assert matched is not None


def test_debounce_first_call_false():
    assert _is_debounced(99, "u", "k") is False


def test_debounce_second_call_true():
    _is_debounced(100, "u", "k")
    assert _is_debounced(100, "u", "k") is True


def test_debounce_different_chats():
    _is_debounced(200, "u", "k")
    assert _is_debounced(201, "u", "k") is False


def test_debounce_constant():
    assert DEBOUNCE_SECONDS == 600
