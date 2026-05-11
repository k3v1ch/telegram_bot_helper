import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.digest_store import (
    cleanup_old_digests,
    save_digest,
    search_digests,
)

MSK = timezone(timedelta(hours=3))


def test_save_digest_creates_unique_file(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "first", 10, "24h")
    save_digest(tmp_data_dir, "second", 20, "12h")
    files = list((tmp_data_dir / "digests").glob("*.json"))
    assert len(files) >= 1


def test_save_digest_contents(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "test text", 100, "24h")
    files = list((tmp_data_dir / "digests").glob("*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["raw_text"] == "test text"
    assert data["message_count"] == 100
    assert data["period"] == "24h"


def test_save_digest_filename_format(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "x", 1, "7d")
    files = list((tmp_data_dir / "digests").glob("*.json"))
    name = files[0].name
    parts = name.replace(".json", "").split("_")
    assert len(parts) == 3
    assert parts[2] == "7d"


def test_search_finds_keyword_case_insensitive(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "Selectel выведен из БС", 50, "24h")
    results = search_digests(tmp_data_dir, "selectel")
    assert len(results) == 1
    assert any("Selectel" in line for line in results[0]["lines"])


def test_search_finds_russian_keyword(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "Сообщается что выведен IP", 5, "1h")
    results = search_digests(tmp_data_dir, "выведен")
    assert len(results) == 1


def test_search_no_results(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "обычный текст", 10, "1h")
    assert search_digests(tmp_data_dir, "missing") == []


def test_search_respects_max_results(tmp_data_dir: Path):
    digests_dir = tmp_data_dir / "digests"
    digests_dir.mkdir()
    for i in range(10):
        path = digests_dir / f"2026-05-{i + 1:02d}_1200_24h.json"
        path.write_text(
            json.dumps({
                "date": f"2026-05-{i + 1:02d}",
                "period": "24h",
                "raw_text": "Selectel выведен",
                "message_count": 1,
            }),
            encoding="utf-8",
        )
    results = search_digests(tmp_data_dir, "selectel", max_results=3)
    assert len(results) == 3


def test_search_ignores_tmp_files(tmp_data_dir: Path):
    digests_dir = tmp_data_dir / "digests"
    digests_dir.mkdir()
    (digests_dir / "broken.json.tmp").write_text("garbage", encoding="utf-8")
    save_digest(tmp_data_dir, "Selectel выведен", 1, "24h")
    results = search_digests(tmp_data_dir, "selectel")
    assert len(results) == 1


def test_cleanup_removes_old(tmp_data_dir: Path):
    digests_dir = tmp_data_dir / "digests"
    digests_dir.mkdir()
    old = {"date": "2020-01-01", "period": "24h", "raw_text": "old", "message_count": 0}
    (digests_dir / "2020-01-01_0000_24h.json").write_text(
        json.dumps(old), encoding="utf-8"
    )
    removed = cleanup_old_digests(tmp_data_dir, days=30)
    assert removed == 1
    assert list(digests_dir.glob("*.json")) == []


def test_cleanup_keeps_recent(tmp_data_dir: Path):
    save_digest(tmp_data_dir, "recent", 1, "24h")
    removed = cleanup_old_digests(tmp_data_dir, days=30)
    assert removed == 0


def test_cleanup_handles_bad_files(tmp_data_dir: Path):
    digests_dir = tmp_data_dir / "digests"
    digests_dir.mkdir()
    (digests_dir / "broken.json").write_text("not json", encoding="utf-8")
    removed = cleanup_old_digests(tmp_data_dir, days=30)
    assert removed == 0
