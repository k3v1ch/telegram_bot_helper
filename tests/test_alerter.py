from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.alerter import (
    DEBOUNCE_SECONDS,
    HIGH_PRIORITY_PHRASES,
    IP_KEYWORDS,
    IP_PATTERN,
    Alerter,
)
from bot.state import BotState


@pytest.fixture
def alerter(tmp_data_dir: Path):
    config = MagicMock()
    config.source_chat_id = -100123
    state = BotState(tmp_data_dir, alerts_default=True)
    return Alerter(MagicMock(), MagicMock(), config, state)


def test_ip_pattern_matches_classic_ip():
    assert IP_PATTERN.search("выведен 1.2.3.4")


def test_ip_pattern_matches_subnet_with_xxx():
    assert IP_PATTERN.search("subnet 10.0.0.xxx")


def test_ip_pattern_matches_with_star():
    assert IP_PATTERN.search("subnet 10.0.0.*")


def test_ip_pattern_no_match_without_ip():
    assert not IP_PATTERN.search("just text here")


def test_check_alert_high_priority_phrase(alerter):
    assert alerter._check_alert("Сервер выведен из бс срочно", "user1") is True


def test_check_alert_each_high_priority_phrase(alerter):
    for i, phrase in enumerate(HIGH_PRIORITY_PHRASES):
        assert alerter._check_alert(f"Текст {phrase} ещё", f"user{i}") is True


def test_check_alert_ip_with_keyword(alerter):
    assert alerter._check_alert("1.2.3.4 заблокирован", "user_ip") is True


def test_check_alert_ip_without_keyword(alerter):
    assert alerter._check_alert("сервер на 1.2.3.4 работает", "user_neutral") is False


def test_check_alert_keyword_without_ip(alerter):
    assert alerter._check_alert("что-то заблокирован просто так", "u") is False


def test_check_alert_random_message(alerter):
    assert alerter._check_alert("привет всем как дела", "u") is False


def test_debounce_first_pass(alerter):
    assert alerter._is_debounced("user1", "keyword1") is False


def test_debounce_second_call_blocked(alerter):
    alerter._is_debounced("user1", "keyword1")
    assert alerter._is_debounced("user1", "keyword1") is True


def test_debounce_different_user(alerter):
    alerter._is_debounced("user1", "kw")
    assert alerter._is_debounced("user2", "kw") is False


def test_debounce_different_keyword(alerter):
    alerter._is_debounced("user1", "kw1")
    assert alerter._is_debounced("user1", "kw2") is False


def test_debounce_seconds_constant():
    assert DEBOUNCE_SECONDS == 600
