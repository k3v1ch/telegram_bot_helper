from bot.reader import EMOJI_ONLY, FetchResult


def test_emoji_only_matches_single():
    assert EMOJI_ONLY.match("😀")


def test_emoji_only_matches_multiple():
    assert EMOJI_ONLY.match("👍🔥💯")


def test_emoji_only_matches_with_whitespace():
    assert EMOJI_ONLY.match("  😀  ")


def test_emoji_only_rejects_text():
    assert not EMOJI_ONLY.match("hello")
    assert not EMOJI_ONLY.match("abc")
    assert not EMOJI_ONLY.match("text 😀")


def test_emoji_only_rejects_russian():
    assert not EMOJI_ONLY.match("привет")


def test_fetch_result_dataclass():
    r = FetchResult(messages=[], total_fetched=10, after_stage1=5)
    assert r.total_fetched == 10
    assert r.after_stage1 == 5
    assert r.messages == []
