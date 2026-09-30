from datetime import date, datetime, time

import pytest

from bot.utils import available_dates, day_slots, format_date, leads_to_csv, normalize_phone


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


def test_available_dates_skips_days_off():
    # 28.09.2026 — понедельник, воскресенье (6) — выходной
    days = available_dates(date(2026, 9, 28), days_ahead=7, days_off=(6,))
    assert len(days) == 6
    assert date(2026, 10, 4) not in days


def test_day_slots_excludes_booked_and_past():
    day = date(2026, 10, 1)
    now = datetime(2026, 10, 1, 12, 30)
    slots = day_slots(day, time(10, 0), time(16, 0), 60, booked={"14:00"}, now=now)
    assert slots == ["13:00", "15:00"]


def test_day_slots_last_slot_fits_before_end():
    day = date(2026, 10, 2)
    now = datetime(2026, 10, 1)
    slots = day_slots(day, time(10, 0), time(11, 30), 30, booked=set(), now=now)
    assert slots == ["10:00", "10:30", "11:00"]


def test_format_date():
    assert format_date(date(2026, 10, 1)) == "01.10 (Чт)"


def test_leads_to_csv_excel_friendly():
    data = leads_to_csv([{"id": 1, "name": "Анна", "phone": "+79991234567", "extra": "x"}])
    assert data.startswith("﻿".encode("utf-8"))
    text = data.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("id;created_at;name")
    assert "Анна" in text and "extra" not in text
