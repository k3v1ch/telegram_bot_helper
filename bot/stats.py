import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


def _stats_path(data_dir: Path) -> Path:
    return data_dir / "stats.json"


def load_stats(data_dir: Path) -> dict[str, int]:
    path = _stats_path(data_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load stats")
        return {}


def save_today_count(data_dir: Path, count: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    stats = load_stats(data_dir)
    stats[today] = count
    try:
        _stats_path(data_dir).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to save stats")


def get_yesterday_count(data_dir: Path) -> int | None:
    yesterday = (datetime.now(MSK) - timedelta(days=1)).strftime("%Y-%m-%d")
    return load_stats(data_dir).get(yesterday)
