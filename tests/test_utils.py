from datetime import date, datetime, time

import pytest

from bot.db import STATUSES
from bot.utils import (
    day_slots,
    format_date,
    format_date_long,
    format_phone,
    leads_to_csv,
    normalize_phone,
    reminders_due,
    working_days,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 (999) 123-45-67", "+79991234567"),
        ("89991234567", "+79991234567"),
        ("9991234567", "+79991234567"),
        ("79991234567", "+79991234567"),
        ("12345", None),
        ("+1 202 555 0100", None),
        ("телефон", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_format_phone():
    assert format_phone("+79991234567") == "+7 999 123-45-67"
    assert format_phone("12345") == "12345"


def test_working_days_skip_days_off_and_holidays():
    # 28.09.2026 — понедельник; работаем пн–сб, 30.09 — праздник
    schedule = {day: ((time(10), time(19)),) for day in range(6)}
    days = working_days(date(2026, 9, 28), 7, schedule, frozenset({date(2026, 9, 30)}))
    assert len(days) == 5
    assert date(2026, 10, 4) not in days  # воскресенье
    assert date(2026, 9, 30) not in days


def test_day_slots_excludes_booked_and_too_early():
    day = date(2026, 10, 1)
    slots = day_slots(day, ((time(10), time(16)),), 60, booked={"14:00"}, earliest=datetime(2026, 10, 1, 12, 30))
    assert slots == ["13:00", "15:00"]


def test_day_slots_respect_lunch_break():
    day = date(2026, 10, 1)
    intervals = ((time(10), time(12)), (time(13), time(15)))
    slots = day_slots(day, intervals, 60, booked=set(), earliest=datetime(2026, 9, 30))
    assert slots == ["10:00", "11:00", "13:00", "14:00"]


def test_day_slots_last_slot_fits_before_end():
    day = date(2026, 10, 2)
    slots = day_slots(day, ((time(10), time(11, 30)),), 30, booked=set(), earliest=datetime(2026, 10, 1))
    assert slots == ["10:00", "10:30", "11:00"]


def test_format_dates():
    assert format_date(date(2026, 10, 1)) == "01.10 (Чт)"
    assert format_date_long(date(2026, 10, 1)) == "чт, 1 октября"


def make_lead(visit: str, created: str, day_sent: int = 0, hours_sent: int = 0) -> dict:
    visit_date, visit_time = visit.split()
    return {
        "id": 1,
        "visit_date": visit_date,
        "visit_time": visit_time,
        "created_at": created,
        "reminded_day": day_sent,
        "reminded_hours": hours_sent,
    }


NOW = datetime(2026, 10, 5, 12, 0)


def kinds(lead: dict, day_before: bool = True, hours_before: int = 2) -> list[str]:
    return [kind for _, kind in reminders_due([lead], NOW, day_before, hours_before)]


def test_day_reminder_inside_24h():
    assert kinds(make_lead("2026-10-06 11:00", "2026-10-01 10:00")) == ["day"]


def test_no_day_reminder_earlier_than_24h():
    assert kinds(make_lead("2026-10-06 13:00", "2026-10-01 10:00")) == []


def test_hours_reminder_replaces_day_one():
    assert kinds(make_lead("2026-10-05 13:30", "2026-10-01 10:00")) == ["hours"]


def test_reminders_not_repeated():
    assert kinds(make_lead("2026-10-06 11:00", "2026-10-01 10:00", day_sent=1)) == []
    assert kinds(make_lead("2026-10-05 13:30", "2026-10-01 10:00", hours_sent=1)) == []


def test_no_reminder_if_booked_inside_window():
    # Записался сегодня утром на завтра: напоминание «завтра у вас запись» ему не нужно
    assert kinds(make_lead("2026-10-06 10:00", "2026-10-05 11:00")) == []
    # Записался за час: напоминание «за 2 часа» тоже лишнее
    assert kinds(make_lead("2026-10-05 13:00", "2026-10-05 11:55")) == []


def test_reminders_can_be_disabled():
    assert kinds(make_lead("2026-10-06 11:00", "2026-10-01 10:00"), day_before=False) == []
    assert kinds(make_lead("2026-10-05 13:30", "2026-10-01 10:00"), hours_before=0) == ["day"]


def test_leads_to_csv_excel_friendly():
    rows = [{"id": 1, "name": "Анна", "phone": "+79991234567", "status": "confirmed", "extra": "x"}]
    data = leads_to_csv(rows, STATUSES)
    assert data.startswith("﻿".encode())
    text = data.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("№;Создана;Дата визита")
    assert "Анна" in text and "Подтверждена" in text
    assert "📌" not in text and "extra" not in text
