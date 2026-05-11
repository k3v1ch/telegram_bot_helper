import logging
import re

from groq import AsyncGroq

from bot.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты анализируешь логи Telegram-чата русскоязычного сообщества операторов VPN-сервисов.

КОНТЕКСТ (обязательно прочитай):
- БС / белый список / вайтлист — это список IP-адресов российских провайдеров, через которые \
работают сервисы Яндекс, Mail.ru, ВКонтакте, Wildberries, Ozon и другие. \
VPN-операторы арендуют серверы с такими IP чтобы их пользователи могли пользоваться \
российскими сервисами через VPN.
- "Выведен из БС" — IP-адрес или подсеть удалена из белого списка, серверы на этих IP \
перестают работать для российских сервисов. Это КРИТИЧЕСКОЕ событие.
- "Добавлен в БС" — IP добавлен в белый список. Хорошая новость.
- Провайдеры: Selectel, Рег.ру, Hetzner, AEZA, Beget, TimeWeb, RuVDS, Яндекс.Облако, VK Cloud — \
это хостинги где операторы арендуют серверы с белыми IP.
- "Крутить IP" — автоматически перебирать IP-адреса в поисках белых.
- "Выбить IP" — получить/арендовать IP-адрес из белого диапазона.

ПРАВИЛА АНАЛИЗА:
1. Читай весь чат и выдели ТОЛЬКО конкретные факты с последствиями
2. ОБЯЗАТЕЛЬНО показывай время [ЧЧ:ММ] перед каждым пунктом
3. Каждый пункт — законченная мысль на 1-2 предложения, НЕ цитата из чата
4. Если обсуждение не пришло к выводу — пропускай
5. Игнорируй: приветствия, вопросы без ответов, жалобы без фактов, флуд

ФОРМАТ ВЫВОДА:

## 🔴 Критично
(IP выведены из БС, массовые блокировки, сервисы упали)
Пример: [00:20] Подсеть 51.250.x.x выведена из белого списка — серверы на этих IP перестали работать.

## 🟡 Обновления
(изменения у провайдеров, лимиты, цены, новые факты об IP-диапазонах)
Пример: [09:56] Рег.ру ввёл лимит 10-15 VM в сутки даже для верифицированных аккаунтов.

## 🔵 Полезно
(рабочие решения, конкретные советы, технические выводы с практическим применением)
Пример: [09:50] IPv6 доступен у любого оператора и пока не блокируется — актуальная альтернатива.

Секцию пропускай целиком если в ней нечего писать.
Никаких общих фраз, никаких советов "будьте осторожны", только конкретика."""

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
