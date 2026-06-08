import os
from dataclasses import dataclass


PROVIDER_GROQ = "groq"
PROVIDER_MIMO = "mimo"

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    PROVIDER_GROQ: {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "label": "Groq",
    },
    PROVIDER_MIMO: {
        "base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "label": "Xiaomi MiMo",
    },
}


@dataclass
class Config:
    bot_token: str
    admin_user_id: int
    database_url: str
    telegram_api_id: int
    telegram_api_hash: str

    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_label: str

    @classmethod
    def from_env(cls) -> "Config":
        def require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise ValueError(f"Missing required env var: {key}")
            return val

        def opt(key: str) -> str | None:
            v = os.getenv(key)
            v = v.strip() if v else ""
            return v or None

        groq_key = opt("GROQ_API_KEY")
        mimo_key = opt("MIMO_API_KEY")

        if groq_key and mimo_key:
            raise ValueError(
                "Both GROQ_API_KEY and MIMO_API_KEY are set in .env. "
                "Choose ONE provider: leave only one key uncommented, comment out the other."
            )
        if not groq_key and not mimo_key:
            raise ValueError(
                "No LLM provider configured. Set either GROQ_API_KEY or MIMO_API_KEY in .env "
                "(exactly one — comment out the other)."
            )

        if mimo_key:
            provider = PROVIDER_MIMO
            api_key = mimo_key
            base_url = os.getenv("MIMO_BASE_URL") or PROVIDER_DEFAULTS[PROVIDER_MIMO]["base_url"]
            model = os.getenv("MIMO_MODEL") or PROVIDER_DEFAULTS[PROVIDER_MIMO]["model"]
        else:
            provider = PROVIDER_GROQ
            api_key = groq_key  # type: ignore[assignment]
            base_url = os.getenv("GROQ_BASE_URL") or PROVIDER_DEFAULTS[PROVIDER_GROQ]["base_url"]
            model = os.getenv("GROQ_MODEL") or PROVIDER_DEFAULTS[PROVIDER_GROQ]["model"]

        return cls(
            bot_token=require("BOT_TOKEN"),
            admin_user_id=int(require("ADMIN_USER_ID")),
            database_url=require("DATABASE_URL"),
            telegram_api_id=int(require("TELEGRAM_API_ID")),
            telegram_api_hash=require("TELEGRAM_API_HASH"),
            llm_provider=provider,
            llm_api_key=api_key,
            llm_base_url=base_url,
            llm_model=model,
            llm_label=PROVIDER_DEFAULTS[provider]["label"],
        )
