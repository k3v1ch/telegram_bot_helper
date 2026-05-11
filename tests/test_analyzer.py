from bot.analyzer import (
    _count_lines,
    _format_messages,
    _merge_to_max_blocks,
    _split_into_blocks,
    _split_text_into_chunks,
    BLOCK_BOUNDARIES,
    MAX_BLOCKS,
)


def test_split_into_blocks_assigns_to_correct_2h_window():
    msgs = [
        {"time": "01:30", "sender": "A", "text": "x"},
        {"time": "03:15", "sender": "B", "text": "y"},
        {"time": "01:45", "sender": "C", "text": "z"},
    ]
    blocks = _split_into_blocks(msgs)
    assert "00:00–02:00" in blocks
    assert "02:00–04:00" in blocks
    assert len(blocks["00:00–02:00"]) == 2
    assert len(blocks["02:00–04:00"]) == 1


def test_split_into_blocks_empty():
    assert _split_into_blocks([]) == {}


def test_block_boundaries_cover_24h():
    assert BLOCK_BOUNDARIES[0] == (0, 2)
    assert BLOCK_BOUNDARIES[-1] == (22, 24)
    assert len(BLOCK_BOUNDARIES) == 12


def test_merge_to_max_blocks_noop_when_under_limit():
    blocks = {"a": [1], "b": [2]}
    assert _merge_to_max_blocks(blocks, 5) == blocks


def test_merge_to_max_blocks_reduces_count():
    blocks = {f"{h:02d}:00–{h + 2:02d}:00": [1] * (h + 1) for h in range(0, 24, 2)}
    assert len(blocks) == 12
    merged = _merge_to_max_blocks(blocks, MAX_BLOCKS)
    assert len(merged) == MAX_BLOCKS


def test_merge_preserves_all_items():
    blocks = {
        "00:00–02:00": [1, 2, 3],
        "02:00–04:00": [4],
        "04:00–06:00": [5, 6],
    }
    total_before = sum(len(v) for v in blocks.values())
    merged = _merge_to_max_blocks(blocks, 2)
    total_after = sum(len(v) for v in merged.values())
    assert total_before == total_after


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


def test_format_messages_uses_time_sender_text():
    msgs = [
        {"time": "10:00", "sender": "Alice", "text": "hi"},
        {"time": "10:05", "sender": "Bob", "text": "ok"},
    ]
    out = _format_messages(msgs)
    assert out == "[10:00] Alice: hi\n[10:05] Bob: ok"
