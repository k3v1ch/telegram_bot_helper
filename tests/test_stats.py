from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from bot.stats import get_yesterday_count, load_stats, save_today_count

MSK = timezone(timedelta(hours=3))


def test_load_empty(tmp_data_dir: Path):
    assert load_stats(tmp_data_dir) == {}


def test_save_today_count_creates_file(tmp_data_dir: Path):
    save_today_count(tmp_data_dir, 123)
    stats = load_stats(tmp_data_dir)
    assert len(stats) == 1
    assert 123 in stats.values()


def test_save_today_overrides_same_day(tmp_data_dir: Path):
    save_today_count(tmp_data_dir, 10)
    save_today_count(tmp_data_dir, 25)
    stats = load_stats(tmp_data_dir)
    assert list(stats.values()) == [25]


def test_get_yesterday_none_when_no_data(tmp_data_dir: Path):
    assert get_yesterday_count(tmp_data_dir) is None


def test_get_yesterday_returns_value(tmp_data_dir: Path):
    yesterday = (datetime.now(MSK) - timedelta(days=1)).strftime("%Y-%m-%d")
    (tmp_data_dir / "stats.json").write_text(
        f'{{"{yesterday}": 77}}', encoding="utf-8"
    )
    assert get_yesterday_count(tmp_data_dir) == 77


def test_corrupted_stats_returns_empty(tmp_data_dir: Path):
    (tmp_data_dir / "stats.json").write_text("garbage", encoding="utf-8")
    assert load_stats(tmp_data_dir) == {}
