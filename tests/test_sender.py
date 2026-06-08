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
        chat_name="MyChat",
        total_count=100,
        yesterday_count=None,
        period="24h",
        start_time="10:00",
        end_time="11:00",
    )
    assert "MyChat" in out
    assert "100" in out


def test_build_header_weekly_format():
    out = _build_header(
        chat_name="MyChat",
        total_count=500,
        yesterday_count=None,
        period="7d",
        start_time="00:00",
        end_time="23:59",
    )
    assert "MyChat" in out


def test_build_header_diff_arrows_up():
    up = _build_header(
        chat_name="X",
        total_count=100,
        yesterday_count=50,
        period="24h",
        start_time="00:00",
        end_time="00:00",
    )
    assert "▲" in up


def test_build_header_diff_arrows_down():
    down = _build_header(
        chat_name="X",
        total_count=30,
        yesterday_count=50,
        period="24h",
        start_time="00:00",
        end_time="00:00",
    )
    assert "▼" in down


def test_build_header_includes_llm_label():
    out = _build_header(
        chat_name="X",
        total_count=10,
        yesterday_count=None,
        period="24h",
        start_time="00:00",
        end_time="01:00",
        llm_label="Xiaomi MiMo",
    )
    assert "Xiaomi MiMo" in out
    assert "🤖" in out


def test_build_header_omits_llm_label_when_none():
    out = _build_header(
        chat_name="X",
        total_count=10,
        yesterday_count=None,
        period="24h",
        start_time="00:00",
        end_time="01:00",
    )
    assert "🤖" not in out
