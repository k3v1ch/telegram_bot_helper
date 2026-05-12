import pytest

from bot.config import Config


def test_from_env_valid(base_env):
    cfg = Config.from_env()
    assert cfg.telegram_api_id == 12345
    assert cfg.telegram_api_hash == "hashvalue"
    assert cfg.bot_token == "bottoken"
    assert cfg.admin_user_id == 999999
    assert cfg.groq_api_key == "groqkey"
    assert "postgresql" in cfg.database_url


def test_missing_required_raises(base_env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    with pytest.raises(Exception):
        Config.from_env()


def test_missing_bot_token(base_env, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(Exception):
        Config.from_env()
