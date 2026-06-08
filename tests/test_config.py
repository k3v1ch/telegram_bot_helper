import pytest

from bot.config import Config, PROVIDER_DEFAULTS, PROVIDER_GROQ, PROVIDER_MIMO


def test_from_env_valid_groq(base_env):
    cfg = Config.from_env()
    assert cfg.telegram_api_id == 12345
    assert cfg.telegram_api_hash == "hashvalue"
    assert cfg.bot_token == "bottoken"
    assert cfg.admin_user_id == 999999
    assert "postgresql" in cfg.database_url

    assert cfg.llm_provider == PROVIDER_GROQ
    assert cfg.llm_api_key == "groqkey"
    assert cfg.llm_base_url == PROVIDER_DEFAULTS[PROVIDER_GROQ]["base_url"]
    assert cfg.llm_model == PROVIDER_DEFAULTS[PROVIDER_GROQ]["model"]


def test_mimo_provider_selected(base_env, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "mimokey")
    cfg = Config.from_env()
    assert cfg.llm_provider == PROVIDER_MIMO
    assert cfg.llm_api_key == "mimokey"
    assert cfg.llm_base_url == PROVIDER_DEFAULTS[PROVIDER_MIMO]["base_url"]
    assert cfg.llm_model == PROVIDER_DEFAULTS[PROVIDER_MIMO]["model"]


def test_mimo_overrides(base_env, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "mimokey")
    monkeypatch.setenv("MIMO_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MIMO_MODEL", "custom-model")
    cfg = Config.from_env()
    assert cfg.llm_base_url == "https://example.com/v1"
    assert cfg.llm_model == "custom-model"


def test_both_providers_raises(base_env, monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "mimokey")
    with pytest.raises(ValueError, match="Both GROQ_API_KEY and MIMO_API_KEY"):
        Config.from_env()


def test_no_provider_raises(base_env, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(ValueError, match="No LLM provider configured"):
        Config.from_env()


def test_empty_string_keys_treated_as_absent(base_env, monkeypatch):
    # GROQ_API_KEY="   " should be treated as unset; with no other key -> error
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(ValueError, match="No LLM provider configured"):
        Config.from_env()


def test_missing_required_raises(base_env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    with pytest.raises(Exception):
        Config.from_env()


def test_missing_bot_token(base_env, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(Exception):
        Config.from_env()
