"""Настройки бота.

Секреты (токен, ID админов) лежат в .env, всё остальное — услуги, график,
напоминания — в config.toml, который владелец бизнеса может править сам.
"""

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Интервал рабочего времени: (начало, конец)
Interval = tuple[time, time]


@dataclass(frozen=True)
class Service:
    name: str
    price: str = ""

    @property
    def label(self) -> str:
        """Подпись на кнопке: «Стрижка · 1 500 ₽»."""
        return f"{self.name} · {self.price}" if self.price else self.name


def _default_schedule() -> dict[int, tuple[Interval, ...]]:
    # Пн–Сб с 10 до 19, воскресенье — выходной
    return {day: ((time(10, 0), time(19, 0)),) for day in range(6)}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: list[int]
    db_path: str = "data/leads.db"
    # Карточка бизнеса — показывается клиенту в приветствии и напоминаниях
    business_name: str = "Запись на услуги"
    address: str = ""
    phone: str = ""
    timezone: str = "Europe/Moscow"
    services: tuple[Service, ...] = (Service("Консультация"),)
    # Рабочие интервалы по дням недели: 0 — понедельник; дня нет в словаре — выходной
    schedule: dict[int, tuple[Interval, ...]] = field(default_factory=_default_schedule)
    holidays: frozenset[date] = frozenset()
    slot_minutes: int = 60
    days_ahead: int = 14
    # Нельзя записаться ближе, чем за столько минут до начала
    min_minutes_before: int = 60
    max_active_per_user: int = 2
    # Клиент сам отменяет запись не позже, чем за столько часов
    cancel_hours_before: int = 2
    remind_day_before: bool = True
    # Второе напоминание за N часов; 0 — выключено
    remind_hours_before: int = 2

    def now(self) -> datetime:
        """Текущее время бизнеса без tzinfo: сервер может жить в UTC, а салон — в Москве."""
        return datetime.now(ZoneInfo(self.timezone)).replace(tzinfo=None)


class ConfigError(RuntimeError):
    """Ошибка в .env или config.toml с понятным текстом для владельца бота."""


def _parse_ids(raw: str, name: str) -> list[int]:
    try:
        return [int(part) for part in raw.replace(" ", "").split(",") if part]
    except ValueError:
        raise ConfigError(f"{name} должен содержать числа через запятую, сейчас: {raw!r}") from None


def _parse_time(raw: str) -> time:
    hours, minutes = raw.strip().split(":")
    return time(int(hours), int(minutes))


def parse_intervals(raw: str) -> tuple[Interval, ...]:
    """«10:00-14:00, 15:00-19:00» → ((10:00, 14:00), (15:00, 19:00)). Перерыв — через запятую."""
    intervals = []
    for part in raw.split(","):
        if not part.strip():
            continue
        try:
            start_raw, end_raw = part.split("-")
            start, end = _parse_time(start_raw), _parse_time(end_raw)
        except ValueError:
            raise ConfigError(f"Не понял интервал {part.strip()!r}, нужен вид 10:00-19:00") from None
        if start >= end:
            raise ConfigError(f"Интервал {part.strip()!r}: начало должно быть раньше конца")
        intervals.append((start, end))
    return tuple(intervals)


def _parse_schedule(section: dict) -> dict[int, tuple[Interval, ...]]:
    unknown = set(section) - set(WEEKDAY_KEYS)
    if unknown:
        raise ConfigError(f"В [schedule] неизвестные дни: {', '.join(sorted(unknown))}. Нужны mon…sun")
    schedule = {}
    for index, key in enumerate(WEEKDAY_KEYS):
        intervals = parse_intervals(section.get(key, ""))
        if intervals:
            schedule[index] = intervals
    if not schedule:
        raise ConfigError("В [schedule] нет ни одного рабочего дня")
    return schedule


def _parse_services(items: list[dict]) -> tuple[Service, ...]:
    try:
        services = tuple(Service(str(item["name"]).strip(), str(item.get("price", "")).strip()) for item in items)
    except KeyError:
        raise ConfigError("У каждой услуги в [[services]] должно быть поле name") from None
    if not services:
        raise ConfigError("Добавьте хотя бы одну услугу в [[services]]")
    return services


def settings_from_toml(data: dict, bot_token: str, admin_ids: list[int], db_path: str) -> Settings:
    business = data.get("business", {})
    booking = data.get("booking", {})
    reminders = data.get("reminders", {})
    timezone = business.get("timezone", "Europe/Moscow")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"Неизвестный часовой пояс {timezone!r}. Пример: Europe/Moscow") from None
    try:
        holidays = frozenset(date.fromisoformat(day) for day in booking.get("holidays", []))
    except ValueError:
        raise ConfigError('holidays: даты пишутся так: "2026-12-31"') from None

    defaults = Settings(bot_token, admin_ids)
    return Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        db_path=db_path,
        business_name=business.get("name", defaults.business_name),
        address=business.get("address", ""),
        phone=business.get("phone", ""),
        timezone=timezone,
        services=_parse_services(data.get("services", [])),
        schedule=_parse_schedule(data.get("schedule", {})),
        holidays=holidays,
        slot_minutes=int(booking.get("slot_minutes", defaults.slot_minutes)),
        days_ahead=int(booking.get("days_ahead", defaults.days_ahead)),
        min_minutes_before=int(booking.get("min_minutes_before", defaults.min_minutes_before)),
        max_active_per_user=int(booking.get("max_active_per_user", defaults.max_active_per_user)),
        cancel_hours_before=int(booking.get("cancel_hours_before", defaults.cancel_hours_before)),
        remind_day_before=bool(reminders.get("day_before", defaults.remind_day_before)),
        remind_hours_before=int(reminders.get("hours_before", defaults.remind_hours_before)),
    )


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise ConfigError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните.")

    # Без админов заявки молча копились бы в базе — лучше сразу остановиться
    admin_ids = _parse_ids(os.getenv("ADMIN_IDS", ""), "ADMIN_IDS")
    if not admin_ids:
        raise ConfigError("Не задан ADMIN_IDS — некому отправлять заявки. Узнать свой ID: @userinfobot.")

    config_path = Path(os.getenv("CONFIG_PATH", "config.toml"))
    if not config_path.exists():
        raise ConfigError(f"Нет файла {config_path}. Скопируйте config.example.toml в config.toml и заполните.")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"Ошибка в {config_path}: {error}") from None

    return settings_from_toml(data, token, admin_ids, os.getenv("DB_PATH", "data/leads.db"))
