import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


class BotState:
    def __init__(self, data_dir: Path, alerts_default: bool):
        self._path = data_dir / "state.json"
        self._data = self._load(alerts_default)

    def _load(self, alerts_default: bool) -> dict:
        defaults = {
            "alerts_enabled": alerts_default,
            "last_run": None,
            "last_count": 0,
            "next_run": None,
        }
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                defaults.update(saved)
            except Exception:
                logger.exception("Failed to load state.json, using defaults")
        return defaults

    def _save(self) -> None:
        atomic_write_json(self._path, self._data)

    @property
    def alerts_enabled(self) -> bool:
        return self._data["alerts_enabled"]

    def toggle_alerts(self) -> bool:
        self._data["alerts_enabled"] = not self._data["alerts_enabled"]
        self._save()
        return self._data["alerts_enabled"]

    @property
    def last_run(self) -> str | None:
        return self._data.get("last_run")

    @property
    def last_count(self) -> int:
        return self._data.get("last_count", 0)

    @property
    def next_run(self) -> str | None:
        return self._data.get("next_run")

    def record_run(self, count: int) -> None:
        self._data["last_run"] = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
        self._data["last_count"] = count
        self._save()

    def set_next_run(self, dt: datetime) -> None:
        self._data["next_run"] = dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M")
        self._save()
