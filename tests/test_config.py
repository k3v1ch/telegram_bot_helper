import pytest

from bot.config import Config


def test_from_env_valid(base_env):
    cfg = Config.from_env()
    assert cfg.telegram_api_id == 12345
    assert cfg.source_chat_id == -1001234567890
    assert cfg.source_topic_id == 155
    assert cfg.dest_chat_id == -1001234567890
    assert cfg.dest_topic_id == 220
    assert cfg.admin_user_id == 999999
    assert cfg.lookback_hours == 24
    assert cfg.digest_time == "09:00"
    assert cfg.alerts_enabled_default is True
    assert cfg.weekly_digest_day == "mon"
    assert cfg.health_port == 8080


def test_missing_required_raises(base_env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM_API_ID"):
        Config.from_env()


def test_invalid_source_format(monkeypatch, base_env):
    monkeypatch.setenv("SOURCE", "no_colon_here")
    with pytest.raises(ValueError, match="must be in format"):
        Config.from_env()


def test_optional_overrides(monkeypatch, base_env):
    monkeypatch.setenv("DIGEST_TIME", "07:30")
    monkeypatch.setenv("LOOKBACK_HOURS", "12")
    monkeypatch.setenv("WEEKLY_DIGEST_DAY", "FRIDAY")
    monkeypatch.setenv("ALERTS_ENABLED", "false")
    monkeypatch.setenv("HEALTH_PORT", "9090")

    cfg = Config.from_env()
    assert cfg.digest_time == "07:30"
    assert cfg.lookback_hours == 12
    assert cfg.weekly_digest_day == "fri"
    assert cfg.alerts_enabled_default is False
    assert cfg.health_port == 9090


def test_digest_hour_minute_properties(base_env, monkeypatch):
    monkeypatch.setenv("DIGEST_TIME", "14:25")
    cfg = Config.from_env()
    assert cfg.digest_hour == 14
    assert cfg.digest_minute == 25
