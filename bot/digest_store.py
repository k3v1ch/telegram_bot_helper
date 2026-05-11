import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _digests_dir(data_dir: Path) -> Path:
    d = data_dir / "digests"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_RETENTION_DAYS = 90


def save_digest(data_dir: Path, digest_text: str, message_count: int, period: str) -> None:
    now = datetime.now(MSK)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M")
    filename = f"{date_str}_{time_str}_{period}.json"

    path = _digests_dir(data_dir) / filename
    data = {
        "date": date_str,
        "time": now.strftime("%H:%M"),
        "period": period,
        "raw_text": digest_text,
        "message_count": message_count,
    }
    if atomic_write_json(path, data):
        logger.info(f"Digest saved to {path.name}")
        cleanup_old_digests(data_dir, days=DEFAULT_RETENTION_DAYS)


def cleanup_old_digests(data_dir: Path, days: int = DEFAULT_RETENTION_DAYS) -> int:
    cutoff = datetime.now(MSK) - timedelta(days=days)
    digests_path = _digests_dir(data_dir)
    removed = 0
    for file in digests_path.glob("*.json"):
        if file.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            date_str = data.get("date")
            if not date_str:
                continue
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=MSK)
            if dt < cutoff:
                file.unlink()
                removed += 1
        except Exception:
            logger.exception(f"Cleanup failed for {file.name}")
    if removed > 0:
        logger.info(f"Cleanup removed {removed} digests older than {days} days")
    return removed


def search_digests(data_dir: Path, keyword: str, max_results: int = 5, max_lines: int = 2) -> list[dict]:
    digests_path = _digests_dir(data_dir)
    keyword_lower = keyword.lower()
    results = []

    files = sorted(
        (f for f in digests_path.glob("*.json") if not f.name.endswith(".tmp")),
        reverse=True,
    )

    for file in files:
        if len(results) >= max_results:
            break
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue

        text = data.get("raw_text", "")
        if keyword_lower not in text.lower():
            continue

        matching_lines = []
        for line in text.split("\n"):
            if keyword_lower in line.lower() and line.strip():
                matching_lines.append(line.strip())
                if len(matching_lines) >= max_lines:
                    break

        if matching_lines:
            date_str = data.get("date", file.stem)
            period = data.get("period", "?")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                formatted = f"{dt.day} {MONTHS_RU[dt.month]} {dt.year}"
            except Exception:
                formatted = date_str

            results.append({
                "date_formatted": formatted,
                "period": period,
                "lines": matching_lines,
            })

    return results
