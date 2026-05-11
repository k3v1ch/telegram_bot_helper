import json
from pathlib import Path

from bot.atomic_io import atomic_write_json


def test_creates_file(tmp_path: Path):
    path = tmp_path / "test.json"
    assert atomic_write_json(path, {"a": 1}) is True
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_no_tmp_left_behind(tmp_path: Path):
    path = tmp_path / "test.json"
    atomic_write_json(path, {"key": "value"})
    assert list(tmp_path.glob("*.tmp")) == []


def test_creates_parent_dirs(tmp_path: Path):
    path = tmp_path / "nested" / "deeper" / "test.json"
    assert atomic_write_json(path, [1, 2, 3]) is True
    assert path.exists()


def test_overwrites_existing(tmp_path: Path):
    path = tmp_path / "test.json"
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}


def test_unicode_content(tmp_path: Path):
    path = tmp_path / "ru.json"
    atomic_write_json(path, {"текст": "Привет"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"текст": "Привет"}
