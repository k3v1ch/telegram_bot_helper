from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def base_env(monkeypatch):
    env = {
        "TELEGRAM_API_ID": "12345",
        "TELEGRAM_API_HASH": "hashvalue",
        "TELEGRAM_PHONE": "+70000000000",
        "SOURCE": "-1001234567890:155",
        "DEST": "-1001234567890:220",
        "GROQ_API_KEY": "groqkey",
        "BOT_TOKEN": "bottoken",
        "ADMIN_USER_ID": "999999",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env
