import asyncio
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_api_key: str | None = None
_base_url: str | None = None
_model: str | None = None
_provider: str | None = None
_label: str | None = None


def init(provider: str, api_key: str, base_url: str, model: str, label: str | None = None) -> None:
    global _api_key, _base_url, _model, _provider, _label
    _provider = provider
    _api_key = api_key
    _base_url = base_url
    _model = model
    _label = label or provider


DETAILED_PROMPT = """\
Ты — внимательный аналитик переписки в Telegram. На вход дают полный сырой лог сообщений за период
в формате `[ЧЧ:ММ] Ник: текст`. Твоя задача — собрать МАКСИМАЛЬНО ПОДРОБНЫЙ структурированный
дайджест на русском языке. У тебя нет жёсткого лимита по длине — пиши столько, сколько нужно,
чтобы ничего важного не упустить.

ПРАВИЛА КАЧЕСТВА:
- Игнорируй флуд, приветствия, оффтоп, шутки без сути, эмоциональные реплики без смысла.
- Пиши безлично (без никнеймов), но факты, числа, ссылки, версии, имена файлов, пути, IP, ID
  передавай ДОСЛОВНО.
- Каждый пункт сопровождай меткой времени `[ЧЧ:ММ]` — той, когда событие реально обсуждалось.
- Группируй связанные сообщения в одну тему (диапазон `[ЧЧ:ММ–ЧЧ:ММ]`).
- Не выдумывай факты, которых нет в логе.
- Если тема обсуждалась поверхностно — отрази 1-2 предложения; если детально — раскрой подробно.

ФОРМАТ ОТВЕТА (используй Markdown):

📌 *Резюме*
[1-3 предложения, главное за период]

## 🔴 Важное
[критические события, инциденты, поломки, дедлайны, срочные новости.
Каждый пункт — развёрнуто, 2-4 предложения: что произошло, последствия, статус.]

## 🟡 Обновления
[новости, релизы, изменения, фичи, объявления, факты.
Каждый пункт — развёрнуто, с конкретикой: версии, даты, что именно изменилось.]

## 🔵 Полезно
[советы, лайфхаки, решения, выводы, рекомендации.
Раскрывай суть совета, не «посоветовали что-то» — а ЧТО именно и зачем.]

## 📖 Подробнее
[Этот блок включай ТОЛЬКО если в логе действительно упомянуто что-то технически содержательное:
инструмент, библиотека, фреймворк, команда, протокол, сервис, баг, фича, конфиг, метод, паттерн.
Выбери 2-5 самых интересных тем и раскрой КАЖДУЮ как мини-инструкцию:

### {Название темы}
- **Что это:** 1-2 предложения простым языком.
- **Зачем нужно:** в каких задачах применяется, какие проблемы решает.
- **Как использовать:** конкретные шаги, команды, флаги, минимальный пример конфига/кода
  в блоке кода (```), ссылки на официальную доку если упоминались.
- **На что обратить внимание:** подводные камни, аналоги, ограничения — но ТОЛЬКО если в логе
  об этом действительно говорили или ты уверенно знаешь.

Если в логе технически интересного нет — пропусти весь блок целиком вместе с заголовком.]

Любую секцию, в которой нечего писать, пропускай полностью."""


WEEKLY_PROMPT = """\
Ты — внимательный аналитик переписки в Telegram. На вход дают сырой лог сообщений за НЕДЕЛЮ
в формате `[ЧЧ:ММ] Ник: текст` (по дням подряд). Сделай ПОДРОБНЫЙ еженедельный дайджест на русском.

ПРАВИЛА:
- Раскрывай темы развёрнуто, без жёсткого лимита по длине.
- Группируй связанные сообщения в одну тему — давай каждой теме временной диапазон, а не
  отдельные метки на каждый чих.
- Пиши безлично; факты, числа, ссылки, версии, имена файлов — передавай дословно.
- Не выдумывай.
- Игнорируй флуд, приветствия, оффтоп.

ФОРМАТ ОТВЕТА (Markdown):

📌 *Резюме недели*
[2-4 предложения, главное за неделю]

## 🔴 Важное
[ключевые события недели — детально: что произошло, к чему привело, статус.]

## 🟡 Обновления
[новости, релизы, изменения, тренды — развёрнуто, с конкретикой.]

## 🔵 Полезно
[советы, решения, выводы, проверенные рецепты — раскрывай суть.]

## 📖 Подробнее
[3-7 самых интересных тем недели. Для КАЖДОЙ:

### {Название темы}
- **Что это:** 1-2 предложения.
- **Зачем нужно:** применение, какие проблемы решает.
- **Как использовать:** команды, флаги, минимальный пример (```), ссылки на доки.
- **Контекст обсуждения:** что именно говорили в чате — выводы, разногласия, проверенные рецепты.

Если технически интересного нет — пропусти весь блок целиком.]

Если в каком-то блоке писать нечего — пропускай его."""


API_TIMEOUT = 180.0
RETRY_DELAY = 10
MAX_RETRIES = 2
MAX_OUTPUT_TOKENS = 8192
# Conservative chunk size: even with mimo's huge token budget, the server tends to
# stall on >100k-char prompts. 60k chars ≈ 15k input tokens — comfortable for one call.
INPUT_CHUNK_CHARS = 60_000


def _format_messages(messages: list[dict]) -> str:
    return "\n".join(f"[{m['time']}] {m['sender']}: {m['text']}" for m in messages)


def _split_text_into_chunks(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
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


async def _call_llm(
    client: AsyncOpenAI,
    system_prompt: str,
    user_content: str,
) -> str | None:
    assert _model is not None
    user_msg = (
        "Ниже сырой лог Telegram-чата за период. Составь дайджест по правилам выше "
        "и ничего важного не упусти.\n\n"
        f"{user_content}"
    )
    payload = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):  # initial + MAX_RETRIES retries
        try:
            response = await client.chat.completions.create(
                model=_model,
                temperature=0.3,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=payload,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_exc = e
            if attempt > MAX_RETRIES:
                break
            logger.warning(
                "analyzer: call failed (attempt %d/%d), sleeping %ds: %r",
                attempt,
                MAX_RETRIES + 1,
                RETRY_DELAY,
                e,
            )
            await asyncio.sleep(RETRY_DELAY)
    logger.error(
        "analyzer: LLM call failed after %d attempts (provider=%s model=%s): %r",
        MAX_RETRIES + 1,
        _provider,
        _model,
        last_exc,
    )
    return None


async def analyze(
    messages: list[dict],
    custom_prompt: str | None = None,
    weekly: bool = False,
) -> tuple[str, int]:
    """Single-pass detailed digest.

    Returns (digest_text, useful_count). useful_count = original message count since the
    pipeline no longer pre-filters; the LLM decides itself what's noteworthy.
    """
    if _api_key is None or _base_url is None or _model is None:
        raise RuntimeError("analyzer.init(...) must be called before analyze()")

    if not messages:
        return ("💤 За период ничего важного не произошло", 0)

    total = len(messages)
    full_log = _format_messages(messages)

    if custom_prompt:
        system_prompt = custom_prompt
    elif weekly:
        system_prompt = WEEKLY_PROMPT
    else:
        system_prompt = DETAILED_PROMPT

    client = AsyncOpenAI(
        api_key=_api_key,
        base_url=_base_url,
        timeout=API_TIMEOUT,
        max_retries=0,  # we handle retries ourselves in _call_llm
    )

    pieces = _split_text_into_chunks(full_log, INPUT_CHUNK_CHARS)
    logger.info(
        "analyzer: provider=%s model=%s msgs=%d chars=%d pieces=%d weekly=%s custom=%s",
        _provider,
        _model,
        total,
        len(full_log),
        len(pieces),
        weekly,
        custom_prompt is not None,
    )

    if len(pieces) == 1:
        digest = await _call_llm(client, system_prompt, pieces[0])
        if digest is None:
            return ("⚠️ Ошибка при генерации дайджеста", total)
        return (digest, total)

    partials: list[str] = []
    for i, piece in enumerate(pieces, 1):
        logger.info("analyzer: piece %d/%d (%d chars)", i, len(pieces), len(piece))
        out = await _call_llm(client, system_prompt, piece)
        if out:
            partials.append(out.strip())

    if not partials:
        return ("⚠️ Ошибка при генерации дайджеста", total)
    if len(partials) == 1:
        return (partials[0], total)

    merge_prompt = (
        system_prompt
        + "\n\nНиже даны несколько готовых частей дайджеста по одному и тому же периоду. "
        "Объедини их в один цельный дайджест, сохраняя ВСЮ важную информацию, объединяя дубли, "
        "сохраняя метки времени и сохраняя структуру секций."
    )
    merge_input = "\n\n---\n\n".join(partials)
    merged = await _call_llm(client, merge_prompt, merge_input)
    if merged is None:
        return ("\n\n".join(partials), total)
    return (merged, total)
