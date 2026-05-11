import asyncio
import logging
from dataclasses import dataclass

from groq import AsyncGroq

from bot.config import Config

logger = logging.getLogger(__name__)

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
## 🔴 Критично
(IP выведены из БС, массовые блокировки, сервисы упали)

## 🟡 Обновления
(изменения у провайдеров, лимиты, цены, новые факты об IP-диапазонах)

## 🔵 Полезно
(рабочие решения, технические выводы, конкретные рекомендации)

Секцию пропускай если в ней нечего писать. Никаких общих фраз."""

MAX_BLOCK_CHARS = 4000
BLOCK_HOURS = 2
BLOCK_DELAY = 1.5

BLOCK_BOUNDARIES = [(h, h + BLOCK_HOURS) for h in range(0, 24, BLOCK_HOURS)]


@dataclass
class AnalysisResult:
    text: str
    after_stage2: int


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


async def analyze_messages(messages: list[dict], config: Config) -> AnalysisResult:
    blocks = {label: msgs for label, msgs in _split_into_blocks(messages).items() if msgs}

    if not blocks:
        return AnalysisResult(text="💤 За период ничего важного не произошло", after_stage2=0)

    client = AsyncGroq(api_key=config.groq_api_key)

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
                    model="llama-3.3-70b-versatile",
                    max_tokens=800,
                    temperature=0.1,
                    messages=[
                        {"role": "system", "content": FILTER_PROMPT},
                        {"role": "user", "content": chunk},
                    ],
                )
                result = response.choices[0].message.content.strip()
                call_count += 1
            except Exception:
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
        return AnalysisResult(text="💤 За период ничего важного не произошло", after_stage2=0)

    # --- Stage 3: Final analysis ---
    combined = "\n\n".join(filtered_lines)
    logger.info(f"Stage 3: {len(combined)} chars of filtered content")

    await asyncio.sleep(BLOCK_DELAY)

    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1500,
            temperature=0.3,
            messages=[
                {"role": "system", "content": FINAL_PROMPT},
                {"role": "user", "content": f"Проанализируй следующие отфильтрованные сообщения и составь дайджест:\n\n{combined}"},
            ],
        )
        digest = response.choices[0].message.content
        logger.info("Stage 3 complete")
    except Exception:
        logger.exception("Stage 3 failed")
        return AnalysisResult(text="⚠️ Ошибка при финальном анализе", after_stage2=after_stage2)

    return AnalysisResult(text=digest, after_stage2=after_stage2)
