import pytest

from bot.scheduler import _period_label, parse_chat_topic


def test_parse_chat_topic_group_with_topic():
    assert parse_chat_topic("-1003332852289:155") == (-1003332852289, 155)


def test_parse_chat_topic_bare_user_id():
    assert parse_chat_topic("635544292") == (635544292, None)


def test_parse_chat_topic_strips_whitespace():
    assert parse_chat_topic("  -100:5  ") == (-100, 5)


def test_parse_chat_topic_positive_chat():
    assert parse_chat_topic("123:456") == (123, 456)


def test_parse_chat_topic_invalid_raises():
    with pytest.raises(ValueError):
        parse_chat_topic("abc")


def test_period_label_hours():
    assert _period_label(24) == "24h"
    assert _period_label(1) == "1h"


def test_period_label_weekly():
    assert _period_label(168) == "7d"
