from bot.sender import MAX_MSG_LENGTH, _build_header, _split_message, sanitize_error


def test_sanitize_error_truncates():
    long = "x" * 1000
    result = sanitize_error(long)
    assert len(result) <= 301


def test_sanitize_error_strips_newlines():
    result = sanitize_error("line1\nline2\rline3")
    assert "\n" not in result
    assert "\r" not in result


def test_sanitize_error_short_unchanged():
    assert sanitize_error("short") == "short"


def test_sanitize_error_handles_exception_object():
    err = RuntimeError("boom")
    assert "boom" in sanitize_error(err)


def test_split_message_short():
    assert _split_message("short") == ["short"]


def test_split_message_long_respects_max():
    text = ("a\n" * 5000)[:5000]
    chunks = _split_message(text)
    assert all(len(c) <= MAX_MSG_LENGTH for c in chunks)


def test_split_message_preserves_content():
    text = "abc\n" * 2000
    chunks = _split_message(text)
    merged = "\n".join(chunks)
    assert merged.count("abc") == text.count("abc")


def test_build_header_basic():
    out = _build_header(
        source_chat_name="MyChat",
        message_count=100,
        start_time="10:00",
        end_time="11:00",
        yesterday_count=None,
    )
    assert "MyChat" in out
    assert "100" in out
    assert "10:00" in out
    assert "━━━" in out


def test_build_header_weekly_format():
    out = _build_header(
        source_chat_name="MyChat",
        message_count=500,
        start_time="00:00",
        end_time="23:59",
        yesterday_count=None,
        weekly=True,
    )
    assert "Еженедельный" in out


def test_build_header_pinned_preview():
    out = _build_header(
        source_chat_name="X",
        message_count=1,
        start_time="00:00",
        end_time="00:00",
        yesterday_count=None,
        pinned_preview="новый закреп",
    )
    assert "Закреп обновлён" in out
    assert "новый закреп" in out


def test_build_header_diff_arrows():
    up = _build_header("X", 100, "00:00", "00:00", yesterday_count=50)
    assert "▲" in up
    down = _build_header("X", 30, "00:00", "00:00", yesterday_count=50)
    assert "▼" in down
    eq = _build_header("X", 50, "00:00", "00:00", yesterday_count=50)
    assert "= 0" in eq
