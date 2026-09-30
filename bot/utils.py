"""Чистые функции без Telegram: телефон, слоты записи, CSV. Их удобно тестировать."""

import csv
import io
import re
from datetime import date, datetime, time, timedelta

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def normalize_phone(raw: str) -> str | None:
    """Приводит российский номер к виду +7XXXXXXXXXX. Возвращает None, если номер некорректный."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    else:
        return None
    return "+" + digits


def available_dates(today: date, days_ahead: int, days_off: tuple[int, ...]) -> list[date]:
    """Рабочие дни на ближайшие days_ahead дней, начиная с сегодняшнего."""
    days = (today + timedelta(days=i) for i in range(days_ahead))
    return [d for d in days if d.weekday() not in days_off]


def day_slots(
    day: date,
    start: time,
    end: time,
    slot_minutes: int,
    booked: set[str],
    now: datetime,
) -> list[str]:
    """Свободные слоты на день в формате ЧЧ:ММ. Прошедшие и занятые отбрасываются."""
    slots = []
    current = datetime.combine(day, start)
    finish = datetime.combine(day, end)
    step = timedelta(minutes=slot_minutes)
    while current + step <= finish:
        label = current.strftime("%H:%M")
        if current > now and label not in booked:
            slots.append(label)
        current += step
    return slots


def format_date(day: date) -> str:
    return f"{day.strftime('%d.%m')} ({WEEKDAYS[day.weekday()]})"


def leads_to_csv(rows: list[dict]) -> bytes:
    """CSV в UTF-8 с BOM и разделителем «;» — так файл сразу открывается в Excel."""
    buffer = io.StringIO()
    fields = ["id", "created_at", "name", "phone", "service", "visit_date", "visit_time", "status", "user_id"]
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
