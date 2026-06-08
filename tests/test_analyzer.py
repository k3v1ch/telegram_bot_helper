import pytest

from bot import analyzer
from bot.analyzer import (
    _count_lines,
    _format_messages,
    _split_text_into_chunks,
    DETAILED_PROMPT,
    WEEKLY_PROMPT,
)


def test_format_messages_uses_time_sender_text():
    msgs = [
        {"time": "10:00", "sender": "Alice", "text": "hi"},
        {"time": "10:05", "sender": "Bob", "text": "ok"},
    ]
    out = _format_messages(msgs)
    assert out == "[10:00] Alice: hi\n[10:05] Bob: ok"


def test_split_text_into_chunks_short():
    assert _split_text_into_chunks("hello", 100) == ["hello"]


def test_split_text_into_chunks_breaks_at_newlines():
    text = "aaa\nbbb\nccc\nddd"
    chunks = _split_text_into_chunks(text, 7)
    assert all(len(c) <= 7 for c in chunks)
    assert "aaa" in chunks[0]


def test_split_text_into_chunks_no_newline_hard_split():
    text = "x" * 25
    chunks = _split_text_into_chunks(text, 10)
    assert len(chunks) >= 2


def test_count_lines_counts_non_empty():
    assert _count_lines("a\nb\n\nc") == 3
    assert _count_lines("") == 0
    assert _count_lines("\n\n\n") == 0
    assert _count_lines("single") == 1


def test_prompts_have_detailed_section():
    assert "📖 Подробнее" in DETAILED_PROMPT
    assert "📖 Подробнее" in WEEKLY_PROMPT
    assert "Что это" in DETAILED_PROMPT
    assert "Как использовать" in DETAILED_PROMPT


def test_analyze_uninitialized_raises():
    analyzer._api_key = None
    analyzer._base_url = None
    analyzer._model = None
    import asyncio
    with pytest.raises(RuntimeError, match="analyzer.init"):
        asyncio.run(analyzer.analyze([{"time": "10:00", "sender": "A", "text": "x"}]))


def test_analyze_empty_returns_placeholder():
    analyzer.init(provider="groq", api_key="k", base_url="https://example.com/v1", model="m")
    import asyncio
    digest, count = asyncio.run(analyzer.analyze([]))
    assert "💤" in digest
    assert count == 0
