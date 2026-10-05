import tomllib
from datetime import date, time
from pathlib import Path

import pytest

from bot import config
from bot.config import ConfigError, Service, parse_intervals, settings_from_toml

EXAMPLE = """
[business]
name = "Барбершоп"
timezone = "Asia/Yekaterinburg"

[[services]]
name = "Стрижка"
price = "1 500 ₽"

[[services]]
name = "Борода"

[schedule]
mon = "10:00-14:00, 15:00-19:00"
sat = "11:00-16:00"

[booking]
slot_minutes = 30
holidays = ["2026-12-31"]

[reminders]
hours_before = 0
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    # Не подхватываем настоящий .env разработчика
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("BOT_TOKEN", "ADMIN_IDS", "CONFIG_PATH", "DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(path))


def test_admin_ids_required():
    with pytest.raises(ConfigError, match="ADMIN_IDS"):
        config.load_settings()


def test_admin_ids_must_be_numbers(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "@my_login")
    with pytest.raises(ConfigError, match="числа через запятую"):
        config.load_settings()


def test_missing_config_file_explained(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "nope.toml"))
    with pytest.raises(ConfigError, match="config.example.toml"):
        config.load_settings()


def test_settings_parsed(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1, 2")
    settings = config.load_settings()
    assert settings.admin_ids == [1, 2]
    assert settings.services == (Service("Стрижка", "1 500 ₽"), Service("Борода"))
    assert settings.services[0].label == "Стрижка · 1 500 ₽"
    assert settings.services[1].label == "Борода"
    assert settings.schedule == {
        0: ((time(10), time(14)), (time(15), time(19))),
        5: ((time(11), time(16)),),
    }
    assert settings.holidays == {date(2026, 12, 31)}
    assert settings.slot_minutes == 30
    assert settings.timezone == "Asia/Yekaterinburg"
    assert settings.remind_hours_before == 0
    assert settings.remind_day_before is True


def test_example_config_is_valid():
    # Файл-образец из репозитория должен загружаться без ошибок
    text = (Path(__file__).parent.parent / "config.example.toml").read_text(encoding="utf-8")
    settings = settings_from_toml(tomllib.loads(text), "42:TEST", [1], "x.db")
    assert len(settings.services) == 4
    assert 6 not in settings.schedule  # воскресенье — выходной


@pytest.mark.parametrize(
    ("raw", "message"),
    [("10-19", "10:00-19:00"), ("19:00-10:00", "раньше конца"), ("10:00", "10:00-19:00")],
)
def test_bad_interval_explained(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_intervals(raw)


BASE = {"services": [{"name": "A"}], "schedule": {"mon": "10:00-11:00"}}


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"business": {"timezone": "Mars/Base"}}, "часовой пояс"),
        ({"services": []}, "услугу"),
        ({"services": [{"price": "1"}]}, "name"),
        ({"schedule": {"monday": "10:00-11:00"}}, "неизвестные дни"),
        ({"schedule": {}}, "рабочего дня"),
        ({"booking": {"holidays": ["31.12"]}}, "holidays"),
    ],
)
def test_bad_toml_explained(patch, message):
    with pytest.raises(ConfigError, match=message):
        settings_from_toml({**BASE, **patch}, "42:TEST", [1], "x.db")
