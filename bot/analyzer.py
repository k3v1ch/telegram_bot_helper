import logging
import re

from groq import AsyncGroq

from bot.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are analyzing a Telegram chat of Russian VPN operators discussing whitelists (белые списки/БС), \
hosting, and IP addresses. Your job: extract ONLY actionable, factual information.

STRICT RULES:
- IGNORE: greetings, questions without answers, complaints, off-topic, memes, single-word replies
- INCLUDE ONLY: confirmed facts, announcements, specific IP/subnet news, provider updates, \
technical findings with clear conclusions
- Each item must be a COMPLETE thought, not a chat fragment
- Summarize multi-message discussions into ONE coherent sentence
- If something was discussed but no conclusion reached — skip it entirely
- Times: show only the START time of the discussion, not every message

Format:
## 🔴 Важное (IP выведены/добавлены в БС, критические изменения)
## 🟡 Обновления (проверенные факты о провайдерах, IP-диапазонах, ценах)
## 🔵 Полезное (технические выводы, рабочие конфиги, рекомендации)

If a section is empty — omit it. No section = nothing worth reporting there."""

MAX_INPUT_CHARS = 6000

IP_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.(?:\d{1,3}|xxx|\*)")

PROVIDERS = [
    "рег.ру", "регру", "selectel", "селектел", "hetzner",
    "aeza", "beget", "бегет", "timeweb", "таймвеб",
    "yandex cloud", "я.облако", "vk cloud",
]

KEYWORDS = ["бс", "белый список", "белые списки", "выведен", "добавлен", "заблокирован"]


def _build_mentions_section(messages: list[dict]) -> str:
    ip_hits: dict[str, str] = {}
    provider_hits: dict[str, str] = {}
    keyword_hits: dict[str, str] = {}

    for msg in messages:
        text_lower = msg["text"].lower()
        time = msg["time"]

        for match in IP_PATTERN.finditer(msg["text"]):
            ip = match.group()
            if ip not in ip_hits:
                ip_hits[ip] = time

        for provider in PROVIDERS:
            if provider in text_lower and provider not in provider_hits:
                provider_hits[provider] = time

        for kw in KEYWORDS:
            if kw in text_lower and kw not in keyword_hits:
                keyword_hits[kw] = time

    if not ip_hits and not provider_hits and not keyword_hits:
        return ""

    lines = ["\n## 🔍 Упоминания"]
    if ip_hits:
        items = ", ".join(f"{ip} [{t}]" for ip, t in ip_hits.items())
        lines.append(f"🌐 IP: {items}")
    if provider_hits:
        items = ", ".join(f"{p} [{t}]" for p, t in provider_hits.items())
        lines.append(f"🏢 Провайдеры: {items}")
    if keyword_hits:
        items = ", ".join(f"{kw} [{t}]" for kw, t in keyword_hits.items())
        lines.append(f"🔑 Ключевые слова: {items}")

    return "\n".join(lines)


async def analyze_messages(messages: list[dict], config: Config) -> str:
    chat_log = "\n".join(
        f"[{m['time']}] {m['sender']}: {m['text']}" for m in messages
    )

    if len(chat_log) > MAX_INPUT_CHARS:
        chat_log = chat_log[-MAX_INPUT_CHARS:]
        first_newline = chat_log.find("\n")
        if first_newline != -1:
            chat_log = chat_log[first_newline + 1:]

    client = AsyncGroq(api_key=config.groq_api_key)

    logger.info(f"Sending {len(messages)} messages ({len(chat_log)} chars) to Groq for analysis")

    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chat_log},
        ],
    )

    result = response.choices[0].message.content
    logger.info("Analysis complete")

    mentions = _build_mentions_section(messages)
    if mentions:
        result += mentions

    return result
