import asyncio
import logging

from groq import AsyncGroq

logger = logging.getLogger(__name__)

_groq_api_key: str | None = None


def init(api_key: str) -> None:
    global _groq_api_key
    _groq_api_key = api_key

FILTER_PROMPT = """\
Ты фильтруешь сырой лог чата VPN-операторов.
Контекст: БС/белый список — IP-адреса российских провайдеров для работы \
российских сервисов через VPN. "Выведен из БС" — критично.

Твоя задача: из входящего списка сообщений оставить ТОЛЬКО те строки \
которые содержат конкретную информацию:
- Факты об IP-адресах и подсетях (добавлены/выведены из БС)
- Факты о провайдерах (лимиты, блокировки, цены, доступность)
- Технические решения и выводы
- Важные объявления

Удали: флуд, приветствия, вопросы без ответов, оффтоп, \
споры без вывода, обсуждение не по теме VPN/IP.

Верни ТОЛЬКО отфильтрованные строки в оригинальном формате [ЧЧ:ММ] Ник: текст.
Ничего не добавляй от себя. Если в блоке нет ничего полезного — ответь: ПУСТО"""

FINAL_PROMPT = """\
Ты анализируешь уже отфильтрованный лог чата VPN-операторов.

КОНТЕКСТ:
- БС / белый список — список IP российских провайдеров через которые работают \
Яндекс, ВКонтакте, Wildberries, Ozon и другие российские сервисы через VPN
- "Выведен из БС" — IP удалён из белого списка, серверы перестают работать. КРИТИЧНО.
- "Добавлен в БС" — IP добавлен в белый список. Хорошая новость.
- "Крутить/выбить IP" — перебирать или получить IP из белого диапазона
- Провайдеры: Selectel, Рег.ру, Hetzner, AEZA, Beget, TimeWeb, RuVDS, Яндекс.Облако

ПРАВИЛА:
- Показывай время [ЧЧ:ММ] перед каждым пунктом
- Никнеймы не упоминай, пиши безлично: "Сообщается что...", "Подтверждено что..."
- Каждый пункт — законченный факт в 1-2 предложения
- Не выдумывай факты которых нет в тексте
- Если несколько сообщений об одном событии — объедини в один пункт

ФОРМАТ:
Перед всеми секциями выведи одну строку — краткое резюме всего дня:
📌 Резюме: [одно предложение максимум 150 символов, самое главное за день]
Пустую строку после резюме, затем секции.

## 🔴 Критично
(IP выведены из БС, массовые блокировки, сервисы упали)

## 🟡 Обновления
(изменения у провайдеров, лимиты, цены, новые факты об IP-диапазонах)

## 🔵 Полезно
(рабочие решения, технические выводы, конкретные рекомендации)

Секцию пропускай если в ней нечего писать. Никаких общих фраз."""

WEEKLY_PROMPT = """\
Ты анализируешь уже отфильтрованный лог чата VPN-операторов.
Это ЕЖЕНЕДЕЛЬНЫЙ дайджест за 7 дней.

КОНТЕКСТ:
- БС / белый список — список IP российских провайдеров через которые работают \
Яндекс, ВКонтакте, Wildberries, Ozon и другие российские сервисы через VPN
- "Выведен из БС" — IP удалён из белого списка, серверы перестают работать. КРИТИЧНО.
- "Добавлен в БС" — IP добавлен в белый список. Хорошая новость.
- Провайдеры: Selectel, Рег.ру, Hetzner, AEZA, Beget, TimeWeb, RuVDS, Яндекс.Облако

Выдели только самые значимые события недели — максимум 10 пунктов.
Группируй похожие события вместе.
Никнеймы не упоминай, пиши безлично.
Не выдумывай факты которых нет в тексте.

ФОРМАТ:
📌 Резюме: [одно предложение, самое главное за неделю]

## 🔴 Критично
(IP выведены из БС, массовые блокировки, сервисы упали)

## 🟡 Обновления
(изменения у провайдеров, лимиты, цены, новые факты об IP-диапазонах)

## 🔵 Полезно
(рабочие решения, технические выводы, конкретные рекомендации)

Секцию пропускай если в ней нечего писать. Только самое важное."""

COMPRESS_PROMPT = """\
Сожми следующие уже отфильтрованные факты до самых важных.
Оставь максимум 10 строк. Только конкретные факты с временем.
Формат: [ЧЧ:ММ] факт"""

MAX_BLOCK_CHARS = 6000
MAX_BLOCKS = 6
BLOCK_HOURS = 2
BLOCK_DELAY = 2
RETRY_DELAY = 30
STAGE3_DELAY = 10
STAGE25_CHUNK = 4000
STAGE25_THRESHOLD = 8000
API_TIMEOUT = 60.0

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


def _merge_to_max_blocks(blocks: dict[str, list[dict]], max_blocks: int) -> dict[str, list[dict]]:
    if len(blocks) <= max_blocks:
        return blocks

    labels = sorted(blocks.keys())
    merged: list[tuple[str, list[dict]]] = [(l, blocks[l]) for l in labels]

    while len(merged) > max_blocks:
        min_size = float("inf")
        min_idx = 0
        for i in range(len(merged) - 1):
            combined = len(merged[i][1]) + len(merged[i + 1][1])
            if combined < min_size:
                min_size = combined
                min_idx = i

        l1, m1 = merged[min_idx]
        l2, m2 = merged[min_idx + 1]
        new_label = f"{l1.split('–')[0]}–{l2.split('–')[1]}"
        merged[min_idx] = (new_label, m1 + m2)
        del merged[min_idx + 1]

    return dict(merged)


def _format_messages(messages: list[dict]) -> str:
    return "\n".join(f"[{m['time']}] {m['sender']}: {m['text']}" for m in messages)


def _split_text_into_chunks(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split_pos = text.rfind("\n", 0, max_chars)
        if split_pos == -1:
            split_pos = max_chars
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


def _count_lines(text: str) -> int:
    return len([line for line in text.strip().split("\n") if line.strip()])


async def analyze(
    messages: list[dict],
    custom_prompt: str | None = None,
    weekly: bool = False,
) -> tuple[str, int]:
    if _groq_api_key is None:
        raise RuntimeError("analyzer.init(api_key) must be called before analyze()")

    blocks = {label: msgs for label, msgs in _split_into_blocks(messages).items() if msgs}

    if not blocks:
        return ("💤 За период ничего важного не произошло", 0)

    blocks = _merge_to_max_blocks(blocks, MAX_BLOCKS)
    logger.info(f"Stage 2: {len(blocks)} blocks after merging")

    client = AsyncGroq(api_key=_groq_api_key)

    # --- Stage 2: AI rough filter ---
    filtered_lines: list[str] = []
    call_count = 0

    for label in sorted(blocks):
        block_text = _format_messages(blocks[label])
        chunks = _split_text_into_chunks(block_text, MAX_BLOCK_CHARS)

        for chunk in chunks:
            if call_count > 0:
                await asyncio.sleep(BLOCK_DELAY)

            logger.info(f"Stage 2: block {label} — {len(chunk)} chars")

            try:
                response = await client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    max_tokens=400,
                    temperature=0.1,
                    timeout=API_TIMEOUT,
                    messages=[
                        {"role": "system", "content": FILTER_PROMPT},
                        {"role": "user", "content": chunk},
                    ],
                )
                result = response.choices[0].message.content.strip()
                call_count += 1
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    logger.warning(f"Stage 2: rate limited on block {label}, waiting {RETRY_DELAY}s")
                    await asyncio.sleep(RETRY_DELAY)
                    try:
                        response = await client.chat.completions.create(
                            model="meta-llama/llama-4-scout-17b-16e-instruct",
                            max_tokens=400,
                            temperature=0.1,
                            timeout=API_TIMEOUT,
                            messages=[
                                {"role": "system", "content": FILTER_PROMPT},
                                {"role": "user", "content": chunk},
                            ],
                        )
                        result = response.choices[0].message.content.strip()
                        call_count += 1
                    except Exception:
                        logger.exception(f"Stage 2 retry failed for block {label}, skipping")
                        call_count += 1
                        continue
                else:
                    logger.exception(f"Stage 2 failed for block {label}, skipping")
                    call_count += 1
                    continue

            if result.upper() == "ПУСТО":
                logger.info(f"Stage 2: block {label} — nothing useful")
                continue

            filtered_lines.append(result)

    after_stage2 = sum(_count_lines(chunk) for chunk in filtered_lines)
    logger.info(f"Stage 2 complete: {after_stage2} lines kept from {len(messages)} original messages")

    if not filtered_lines:
        return ("💤 За период ничего важного не произошло", 0)

    # --- Stage 2.5: Compress filtered content for weekly digests ---
    combined = "\n\n".join(filtered_lines)
    if weekly and len(combined) > STAGE25_THRESHOLD:
        logger.info(f"Stage 2.5: {len(combined)} chars exceeds {STAGE25_THRESHOLD}, compressing")
        compress_chunks = _split_text_into_chunks(combined, STAGE25_CHUNK)
        compressed_lines: list[str] = []

        for i, chunk in enumerate(compress_chunks):
            if i > 0:
                await asyncio.sleep(BLOCK_DELAY)

            logger.info(f"Stage 2.5: chunk {i + 1}/{len(compress_chunks)} — {len(chunk)} chars")
            try:
                response = await client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    max_tokens=300,
                    temperature=0.1,
                    timeout=API_TIMEOUT,
                    messages=[
                        {"role": "system", "content": COMPRESS_PROMPT},
                        {"role": "user", "content": chunk},
                    ],
                )
                result = response.choices[0].message.content.strip()
                if result.upper() != "ПУСТО":
                    compressed_lines.append(result)
            except Exception:
                logger.exception(f"Stage 2.5 failed for chunk {i + 1}, keeping original")
                compressed_lines.append(chunk)

        combined = "\n\n".join(compressed_lines)
        logger.info(f"Stage 2.5 complete: {len(combined)} chars after compression")

    # --- Stage 3: Final analysis ---
    if custom_prompt:
        stage3_prompt = custom_prompt
    elif weekly:
        stage3_prompt = WEEKLY_PROMPT
    else:
        stage3_prompt = FINAL_PROMPT
    logger.info(f"Stage 3: {len(combined)} chars of filtered content (weekly={weekly}, custom={custom_prompt is not None})")

    await asyncio.sleep(STAGE3_DELAY)

    stage3_messages = [
        {"role": "system", "content": stage3_prompt},
        {"role": "user", "content": f"Проанализируй следующие отфильтрованные сообщения и составь дайджест:\n\n{combined}"},
    ]

    async def _stage3_call():
        return await client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            max_tokens=1500,
            temperature=0.3,
            timeout=API_TIMEOUT,
            messages=stage3_messages,
        )

    try:
        response = await _stage3_call()
        digest = response.choices[0].message.content
        logger.info("Stage 3 complete")
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower():
            logger.warning(f"Stage 3: rate limited, waiting {RETRY_DELAY}s")
            await asyncio.sleep(RETRY_DELAY)
            try:
                response = await _stage3_call()
                digest = response.choices[0].message.content
                logger.info("Stage 3 complete after retry")
            except Exception:
                logger.exception("Stage 3 retry failed")
                return ("⚠️ Ошибка при финальном анализе", after_stage2)
        else:
            logger.exception("Stage 3 failed")
            return ("⚠️ Ошибка при финальном анализе", after_stage2)

    return (digest, after_stage2)
