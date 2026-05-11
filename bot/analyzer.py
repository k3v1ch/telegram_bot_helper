import asyncio
import logging

from groq import AsyncGroq

from bot.config import Config

logger = logging.getLogger(__name__)

BLOCK_PROMPT = """\
Ты анализируешь фрагмент чата VPN-операторов.
Контекст: БС/белый список — список IP российских провайдеров для работы \
российских сервисов через VPN. "Выведен из БС" — критично, IP перестал работать.
Выдели максимум 5 конкретных фактов из этого отрезка. \
Только факты с временем в формате [ЧЧ:ММ]. Без общих фраз. \
Если ничего важного — ответь одним словом: ПУСТО"""

FINAL_PROMPT = """\
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

MAX_BLOCK_CHARS = 4000
BLOCK_HOURS = 2
BLOCK_DELAY = 1.5

BLOCK_BOUNDARIES = [(h, h + BLOCK_HOURS) for h in range(0, 24, BLOCK_HOURS)]


def _split_into_blocks(messages: list[dict]) -> dict[str, list[dict]]:
    blocks: dict[str, list[dict]] = {}
    for msg in messages:
        hour = int(msg["time"].split(":")[0])
        for start, end in BLOCK_BOUNDARIES:
            if start <= hour < end:
                label = f"{start:02d}:00–{end:02d}:00"
                blocks.setdefault(label, []).append(msg)
                break
    return blocks


def _format_block(messages: list[dict]) -> str:
    text = "\n".join(f"[{m['time']}] {m['sender']}: {m['text']}" for m in messages)
    if len(text) <= MAX_BLOCK_CHARS:
        return text

    head = []
    tail = []
    head_len = 0
    tail_len = 0
    budget = MAX_BLOCK_CHARS - 20

    for msg in messages:
        line = f"[{msg['time']}] {msg['sender']}: {msg['text']}\n"
        if head_len + len(line) < budget // 2:
            head.append(line)
            head_len += len(line)
        else:
            break

    for msg in reversed(messages):
        line = f"[{msg['time']}] {msg['sender']}: {msg['text']}\n"
        if tail_len + len(line) < budget - head_len:
            tail.insert(0, line)
            tail_len += len(line)
        else:
            break

    return "".join(head) + "\n...\n" + "".join(tail)


async def analyze_messages(messages: list[dict], config: Config) -> str:
    blocks = _split_into_blocks(messages)
    non_empty = {label: msgs for label, msgs in blocks.items() if msgs}

    if not non_empty:
        return "💤 За период ничего важного не произошло"

    client = AsyncGroq(api_key=config.groq_api_key)

    if len(non_empty) == 1:
        label, msgs = next(iter(non_empty.items()))
        block_text = _format_block(msgs)
        return await _final_pass(client, block_text)

    summaries = []
    for i, (label, msgs) in enumerate(sorted(non_empty.items())):
        if i > 0:
            await asyncio.sleep(BLOCK_DELAY)

        block_text = _format_block(msgs)
        logger.info(f"Pass 1: block {label} — {len(msgs)} messages, {len(block_text)} chars")

        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=500,
                messages=[
                    {"role": "system", "content": BLOCK_PROMPT},
                    {"role": "user", "content": block_text},
                ],
            )
            result = response.choices[0].message.content.strip()
        except Exception:
            logger.exception(f"Pass 1 failed for block {label}, skipping")
            continue

        if result.upper() == "ПУСТО":
            logger.info(f"Block {label}: nothing important")
            continue

        summaries.append(f"### {label} МСК\n{result}")

    if not summaries:
        return "💤 За период ничего важного не произошло"

    combined = "\n\n".join(summaries)
    logger.info(f"Pass 2: {len(summaries)} block summaries, {len(combined)} chars")

    await asyncio.sleep(BLOCK_DELAY)
    return await _final_pass(client, combined, is_summaries=True)


async def _final_pass(client: AsyncGroq, text: str, *, is_summaries: bool = False) -> str:
    if is_summaries:
        user_content = (
            "Ниже краткие выжимки по временным блокам за весь день.\n"
            "Составь итоговый дайджест по всем блокам.\n\n"
            + text
        )
    else:
        user_content = text

    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": FINAL_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    result = response.choices[0].message.content
    logger.info("Pass 2 complete")
    return result
