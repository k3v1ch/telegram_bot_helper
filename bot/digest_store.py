import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def save_digest(data_dir: Path, digest_text: str, message_count: int, period: str) -> None:
    now = datetime.now(MSK)
    date_str = now.strftime("%Y-%m-%d")
    filename = f"{date_str}.json"

    if period == "7d":
        filename = f"{date_str}-weekly.json"

    path = _digests_dir(data_dir) / filename
    data = {
        "date": date_str,
        "period": period,
        "raw_text": digest_text,
        "message_count": message_count,
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Digest saved to {path.name}")
    except Exception:
        logger.exception("Failed to save digest")


def search_digests(data_dir: Path, keyword: str, max_results: int = 5, max_lines: int = 2) -> list[dict]:
    digests_path = _digests_dir(data_dir)
    keyword_lower = keyword.lower()
    results = []

    files = sorted(digests_path.glob("*.json"), reverse=True)

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
