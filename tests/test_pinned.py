from pathlib import Path

from bot.pinned import _load_pinned, _save_pinned


def test_load_returns_none_when_no_file(tmp_data_dir: Path):
    assert _load_pinned(tmp_data_dir) is None


def test_save_then_load_roundtrip(tmp_data_dir: Path):
    _save_pinned(tmp_data_dir, "2026-05-11 10:00", "test pinned text")
    data = _load_pinned(tmp_data_dir)
    assert data is not None
    assert data["text"] == "test pinned text"
    assert data["date"] == "2026-05-11 10:00"


def test_save_overwrites(tmp_data_dir: Path):
    _save_pinned(tmp_data_dir, "2026-05-10 12:00", "first")
    _save_pinned(tmp_data_dir, "2026-05-11 14:00", "second")
    data = _load_pinned(tmp_data_dir)
    assert data["text"] == "second"


def test_corrupted_pinned_returns_none(tmp_data_dir: Path):
    (tmp_data_dir / "pinned.json").write_text("not json", encoding="utf-8")
    assert _load_pinned(tmp_data_dir) is None
