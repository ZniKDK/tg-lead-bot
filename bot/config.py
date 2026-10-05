"""Настройки бота из переменных окружения (.env)."""

import os
from dataclasses import dataclass, field
from datetime import time

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: list[int]
    db_path: str = "data/leads.db"
    # Рабочее время и длительность слота записи
    work_start: time = time(10, 0)
    work_end: time = time(19, 0)
    slot_minutes: int = 60
    days_ahead: int = 7
    # Выходные дни: 0 — понедельник, 6 — воскресенье
    days_off: tuple[int, ...] = (6,)
    services: list[str] = field(default_factory=list)


def _parse_ids(raw: str, name: str) -> list[int]:
    try:
        return [int(part) for part in raw.replace(" ", "").split(",") if part]
    except ValueError:
        raise RuntimeError(f"{name} должен содержать числа через запятую, сейчас: {raw!r}") from None


def _parse_time(raw: str) -> time:
    hours, minutes = raw.split(":")
    return time(int(hours), int(minutes))


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните.")

    # Без админов заявки молча копились бы в базе — лучше сразу остановиться
    admin_ids = _parse_ids(os.getenv("ADMIN_IDS", ""), "ADMIN_IDS")
    if not admin_ids:
        raise RuntimeError("Не задан ADMIN_IDS — некому отправлять заявки. Узнать свой ID: @userinfobot.")

    services = os.getenv("SERVICES", "Консультация;Диагностика;Ремонт")
    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=os.getenv("DB_PATH", "data/leads.db"),
        work_start=_parse_time(os.getenv("WORK_START", "10:00")),
        work_end=_parse_time(os.getenv("WORK_END", "19:00")),
        slot_minutes=int(os.getenv("SLOT_MINUTES", "60")),
        days_ahead=int(os.getenv("DAYS_AHEAD", "7")),
        days_off=tuple(_parse_ids(os.getenv("DAYS_OFF", "6"), "DAYS_OFF")),
        services=[s.strip() for s in services.split(";") if s.strip()],
    )
