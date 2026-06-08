import html
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import Bot

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
MAX_MSG_LENGTH = 4000

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _arrow(diff: int) -> str:
    if diff > 0:
        return f"▲ +{diff}"
    if diff < 0:
        return f"▼ {diff}"
    return "= 0"


def _is_weekly(period: str) -> bool:
    return period in {"7d", "168h"} or period.endswith("d")


def _build_header(
    chat_name: str,
    total_count: int,
    yesterday_count: int | None,
    period: str,
    start_time: str | None,
    end_time: str | None,
    llm_label: str | None = None,
) -> str:
    now = datetime.now(MSK)
    weekly = _is_weekly(period)

    if weekly:
        week_ago = now - timedelta(days=7)
        date_line = (
            f"📅 {week_ago.day} {MONTHS_RU[week_ago.month]} – "
            f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        )
        title = f"📋 Еженедельный дайджест • {chat_name}"
    else:
        date_str = f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        if start_time and end_time:
            date_line = f"📅 {date_str} • {start_time} – {end_time} МСК"
        else:
            date_line = f"📅 {date_str}"
        title = f"📋 Дайджест • {chat_name}"

    lines = [
        title,
        date_line,
        f"💬 Проанализировано сообщений: {total_count}",
    ]

    if not weekly and yesterday_count is not None:
        lines.append(
            f"📊 Вчера: {yesterday_count} → сегодня: {total_count} ({_arrow(total_count - yesterday_count)})"
        )

    if llm_label:
        lines.append(f"🤖 LLM: {llm_label}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


def _build_header_html(
    chat_name: str,
    total_count: int,
    yesterday_count: int | None,
    period: str,
    start_time: str | None,
    end_time: str | None,
    llm_label: str | None = None,
) -> str:
    """HTML version of the header — title in <b>, body lines plain (HTML-escaped)."""
    now = datetime.now(MSK)
    weekly = _is_weekly(period)

    safe_name = html.escape(chat_name, quote=False)
    if weekly:
        week_ago = now - timedelta(days=7)
        date_line = (
            f"📅 {week_ago.day} {MONTHS_RU[week_ago.month]} – "
            f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        )
        title = f"<b>📋 Еженедельный дайджест • {safe_name}</b>"
    else:
        date_str = f"{now.day} {MONTHS_RU[now.month]} {now.year}"
        if start_time and end_time:
            date_line = f"📅 {date_str} • {start_time} – {end_time} МСК"
        else:
            date_line = f"📅 {date_str}"
        title = f"<b>📋 Дайджест • {safe_name}</b>"

    lines = [
        title,
        date_line,
        f"💬 Проанализировано сообщений: {total_count}",
    ]
    if not weekly and yesterday_count is not None:
        lines.append(
            f"📊 Вчера: {yesterday_count} → сегодня: {total_count} ({_arrow(total_count - yesterday_count)})"
        )
    if llm_label:
        lines.append(f"🤖 LLM: {html.escape(llm_label, quote=False)}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+\-./]*\n?(.*?)```", re.DOTALL)
_INLINE_RE = re.compile(r"`([^`\n]+)`")
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*([^\n*][^*]*?)\*\*", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])")
_ITALIC_USCORE_RE = re.compile(r"(?<![\w_])_([^_\n]+?)_(?![\w_])")
_LINK_RE = re.compile(r"\[([^\]\n]+?)\]\((https?://[^\s)]+?)\)")


def _md_to_html(text: str) -> str:
    """Best-effort Markdown → Telegram HTML.

    Telegram HTML supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href>.
    We extract code blocks first, HTML-escape the rest, convert inline formatting,
    then re-inject escaped code.
    """
    blocks: list[str] = []

    def _stash_fence(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\x00B{len(blocks) - 1}\x00"

    inlines: list[str] = []

    def _stash_inline(m: re.Match) -> str:
        inlines.append(m.group(1))
        return f"\x00I{len(inlines) - 1}\x00"

    text = _FENCE_RE.sub(_stash_fence, text)
    text = _INLINE_RE.sub(_stash_inline, text)

    text = html.escape(text, quote=False)

    text = _HEADING_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_USCORE_RE.sub(r"<i>\1</i>", text)
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)

    for i, blk in enumerate(blocks):
        text = text.replace(
            f"\x00B{i}\x00",
            f"<pre>{html.escape(blk.rstrip(), quote=False)}</pre>",
        )
    for i, inl in enumerate(inlines):
        text = text.replace(
            f"\x00I{i}\x00",
            f"<code>{html.escape(inl, quote=False)}</code>",
        )
    return text


def _strip_html(text: str) -> str:
    """Drop all HTML tags as a plain-text fallback if HTML parsing fails."""
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _balanced(text: str) -> bool:
    """Check that <pre>/<code>/<b>/<i>/<a> tags are balanced in `text`."""
    for tag in ("pre", "code", "b", "i"):
        if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
            return False
    if text.count("<a ") != text.count("</a>"):
        return False
    return True


def _split_html(text: str, max_len: int) -> list[str]:
    """Split HTML-formatted text on paragraph (\\n\\n) and line boundaries while
    keeping the per-chunk tag balance intact. If a chunk would land inside an open
    <pre>...</pre> block, close-and-reopen it across the boundary."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    rest = text
    while len(rest) > max_len:
        split_at = rest.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = rest.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        head = rest[:split_at]
        tail = rest[split_at:].lstrip("\n")

        open_pre = head.count("<pre>") - head.count("</pre>")
        if open_pre > 0:
            head = head + "</pre>"
            tail = "<pre>" + tail
        chunks.append(head)
        rest = tail
    if rest:
        chunks.append(rest)
    return chunks


def _split_message(text: str) -> list[str]:
    """Plain-text splitter — kept for the empty/error helpers and as a fallback."""
    if len(text) <= MAX_MSG_LENGTH:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_MSG_LENGTH:
            chunks.append(text)
            break
        split_pos = text.rfind("\n", 0, MAX_MSG_LENGTH)
        if split_pos == -1:
            split_pos = MAX_MSG_LENGTH
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


async def send_digest(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int | None,
    chat_name: str,
    digest_text: str,
    total_count: int,
    yesterday_count: int | None,
    period: str,
    start_time: str | None = None,
    end_time: str | None = None,
    llm_label: str | None = None,
) -> None:
    header_html = _build_header_html(
        chat_name=chat_name,
        total_count=total_count,
        yesterday_count=yesterday_count,
        period=period,
        start_time=start_time,
        end_time=end_time,
        llm_label=llm_label,
    )
    body_html = _md_to_html(digest_text)
    full_html = header_html + body_html

    thread_id = dest_topic_id or None
    for chunk in _split_html(full_html, MAX_MSG_LENGTH):
        try:
            if not _balanced(chunk):
                raise ValueError("unbalanced tags in chunk")
            await bot.send_message(
                chat_id=dest_chat_id,
                text=chunk,
                message_thread_id=thread_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(
                "HTML send failed for %s (%s), retrying as plain text", chat_name, e
            )
            await bot.send_message(
                chat_id=dest_chat_id,
                text=_strip_html(chunk),
                message_thread_id=thread_id,
                disable_web_page_preview=True,
            )
    logger.info(f"Digest sent to {dest_chat_id} (chat={chat_name}, period={period})")


async def send_empty_notice(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int | None,
    chat_name: str,
    period: str,
) -> None:
    text = f"💤 За период {period} в чате «{chat_name}» ничего важного"
    await bot.send_message(
        chat_id=dest_chat_id,
        text=text,
        message_thread_id=dest_topic_id or None,
    )


def sanitize_error(error: str, max_len: int = 300) -> str:
    safe = str(error).replace("\n", " ").replace("\r", " ").strip()
    if len(safe) > max_len:
        safe = safe[:max_len] + "…"
    return safe


async def send_error(
    bot: Bot,
    dest_chat_id: int,
    dest_topic_id: int | None,
    chat_name: str,
    error: str,
) -> None:
    safe = sanitize_error(error)
    await bot.send_message(
        chat_id=dest_chat_id,
        text=f"⚠️ Ошибка при формировании дайджеста «{chat_name}»:\n{safe}",
        message_thread_id=dest_topic_id or None,
    )
    logger.error(f"Error notification sent for {chat_name}: {safe}")
