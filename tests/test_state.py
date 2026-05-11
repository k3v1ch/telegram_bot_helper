from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.state import BotState

MSK = timezone(timedelta(hours=3))


def test_initial_defaults_when_no_file(tmp_data_dir: Path):
    state = BotState(tmp_data_dir, alerts_default=True)
    assert state.alerts_enabled is True
    assert state.last_run is None
    assert state.last_count == 0
    assert state.next_run is None


def test_initial_alerts_default_false(tmp_data_dir: Path):
    state = BotState(tmp_data_dir, alerts_default=False)
    assert state.alerts_enabled is False


def test_toggle_alerts(tmp_data_dir: Path):
    state = BotState(tmp_data_dir, alerts_default=False)
    assert state.toggle_alerts() is True
    assert state.alerts_enabled is True
    assert state.toggle_alerts() is False
    assert state.alerts_enabled is False


def test_state_persists_across_instances(tmp_data_dir: Path):
    s1 = BotState(tmp_data_dir, alerts_default=True)
    s1.record_run(count=42)
    s1.toggle_alerts()

    s2 = BotState(tmp_data_dir, alerts_default=True)
    assert s2.last_count == 42
    assert s2.alerts_enabled is False


def test_record_run_sets_count_and_time(tmp_data_dir: Path):
    state = BotState(tmp_data_dir, alerts_default=True)
    state.record_run(count=99)
    assert state.last_count == 99
    assert state.last_run is not None


def test_set_next_run_formats_msk(tmp_data_dir: Path):
    state = BotState(tmp_data_dir, alerts_default=True)
    dt = datetime(2026, 5, 11, 10, 0, tzinfo=MSK)
    state.set_next_run(dt)
    assert state.next_run == "2026-05-11 10:00"


def test_corrupted_json_falls_back_to_defaults(tmp_data_dir: Path):
    (tmp_data_dir / "state.json").write_text("not json", encoding="utf-8")
    state = BotState(tmp_data_dir, alerts_default=True)
    assert state.alerts_enabled is True
    assert state.last_count == 0
