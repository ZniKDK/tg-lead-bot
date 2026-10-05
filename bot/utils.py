"""Чистые функции без Telegram: телефон, слоты, напоминания, CSV. Их удобно тестировать."""

import csv
import io
import re
from datetime import date, datetime, time, timedelta

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

Interval = tuple[time, time]


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


def format_phone(phone: str) -> str:
    """+79991234567 → +7 999 123-45-67 — так номер легче прочитать и продиктовать."""
    if len(phone) == 12 and phone.startswith("+7"):
        return f"+7 {phone[2:5]} {phone[5:8]}-{phone[8:10]}-{phone[10:]}"
    return phone


def working_days(
    today: date, days_ahead: int, schedule: dict[int, tuple[Interval, ...]], holidays: frozenset[date]
) -> list[date]:
    """Рабочие дни на ближайшие days_ahead дней, начиная с сегодняшнего."""
    days = (today + timedelta(days=i) for i in range(days_ahead))
    return [d for d in days if d.weekday() in schedule and d not in holidays]


def day_slots(
    day: date,
    intervals: tuple[Interval, ...],
    slot_minutes: int,
    booked: set[str],
    earliest: datetime,
) -> list[str]:
    """Свободные слоты на день в формате ЧЧ:ММ.

    Слот должен целиком помещаться в рабочий интервал. Занятые слоты и те,
    что начинаются раньше earliest (прошедшие или слишком близкие), отбрасываются.
    """
    slots = []
    step = timedelta(minutes=slot_minutes)
    for start, end in intervals:
        current = datetime.combine(day, start)
        finish = datetime.combine(day, end)
        while current + step <= finish:
            label = current.strftime("%H:%M")
            if current >= earliest and label not in booked:
                slots.append(label)
            current += step
    return slots


def format_date(day: date, today: date) -> str:
    """Короткая подпись для кнопки: «Сегодня», «Завтра» или «Чт 01.10»."""
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m')}"


def format_created(raw: str) -> str:
    """«2026-10-05 15:33» из базы → «05.10 в 15:33»."""
    created = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    return f"{created:%d.%m} в {created:%H:%M}"


def format_date_long(day: date) -> str:
    """Подпись для сообщений: «чт, 1 октября»."""
    return f"{WEEKDAYS[day.weekday()].lower()}, {day.day} {MONTHS[day.month - 1]}"


def visit_datetime(lead: dict) -> datetime:
    return datetime.strptime(f"{lead['visit_date']} {lead['visit_time']}", "%Y-%m-%d %H:%M")


def reminders_due(leads: list[dict], now: datetime, day_before: bool, hours_before: int) -> list[tuple[dict, str]]:
    """Какие напоминания пора отправить: список (заявка, "day" | "hours").

    Напоминание не отправляется, если клиент записался уже внутри этого окна:
    кто записался за 3 часа, тому «завтра у вас визит» не нужно.
    """
    due = []
    for lead in leads:
        visit = visit_datetime(lead)
        left = visit - now
        if left <= timedelta(0):
            continue
        booked_ahead = visit - datetime.strptime(lead["created_at"], "%Y-%m-%d %H:%M")
        hours_window = timedelta(hours=hours_before)
        day_window = timedelta(hours=24)

        if hours_before and not lead["reminded_hours"] and left <= hours_window < booked_ahead:
            due.append((lead, "hours"))
        elif (
            day_before
            and not lead["reminded_day"]
            and left <= day_window < booked_ahead
            and (not hours_before or left > hours_window)
        ):
            due.append((lead, "day"))
    return due


def leads_to_csv(rows: list[dict], statuses: dict[str, str]) -> bytes:
    """CSV в UTF-8 с BOM и разделителем «;» — так файл сразу открывается в Excel."""
    columns = {
        "id": "№",
        "created_at": "Создана",
        "visit_date": "Дата визита",
        "visit_time": "Время",
        "service": "Услуга",
        "name": "Имя",
        "phone": "Телефон",
        "status": "Статус",
    }
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(columns.values())
    for row in rows:
        # В таблице статус без эмодзи: «Подтверждена», а не «📌 Подтверждена»
        label = statuses.get(row.get("status"), row.get("status", ""))
        values = {**row, "status": label.split(" ", 1)[-1]}
        writer.writerow(values.get(key, "") for key in columns)
    return buffer.getvalue().encode("utf-8-sig")
