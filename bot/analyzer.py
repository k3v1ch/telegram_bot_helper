import logging

from groq import AsyncGroq

from bot.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an assistant that analyzes Telegram chat logs from a Russian VPN/networking community.
Your task: create a concise daily digest in Russian.

Rules:
- Focus ONLY on meaningful technical/operational information
- Ignore: greetings, "thanks", off-topic chatter, memes, reactions
- Prioritize: announcements, config changes, hosting news, whitelist (белый список) updates,
  new features, warnings, important decisions, links to useful resources
- For each important event: show the TIME (HH:MM MSK) so the reader can find it in chat
- Group by importance:

## 🔴 Важное (critical announcements, breaking changes, urgent warnings)
## 🟡 Обновления (config changes, new features, hosting info)
## 🔵 Обсуждения (useful technical discussions worth knowing about)
## ℹ️ Прочее (minor but notable things)

If a section has nothing — omit it entirely.
If the chat was quiet and nothing important happened — say so briefly.
Format times as [HH:MM] before each item.
Keep each item to 1-3 sentences max."""


async def analyze_messages(messages: list[dict], config: Config) -> str:
    chat_log = "\n".join(
        f"[{m['time']}] {m['sender']}: {m['text']}" for m in messages
    )

    client = AsyncGroq(api_key=config.groq_api_key)

    logger.info(f"Sending {len(messages)} messages to Groq for analysis")

    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chat_log},
        ],
    )

    result = response.choices[0].message.content
    logger.info("Analysis complete")
    return result
