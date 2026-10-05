import pytest

from bot import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Не подхватываем настоящий .env разработчика
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("BOT_TOKEN", "ADMIN_IDS", "DAYS_OFF", "SERVICES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")


def test_admin_ids_required():
    with pytest.raises(RuntimeError, match="ADMIN_IDS"):
        config.load_settings()


def test_admin_ids_must_be_numbers(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "@my_login")
    with pytest.raises(RuntimeError, match="числа через запятую"):
        config.load_settings()


def test_settings_parsed(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1, 2")
    monkeypatch.setenv("SERVICES", "Стрижка; Укладка;")
    settings = config.load_settings()
    assert settings.admin_ids == [1, 2]
    assert settings.services == ["Стрижка", "Укладка"]
    assert settings.days_off == (6,)
