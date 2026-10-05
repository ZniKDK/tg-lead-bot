from datetime import datetime

import aiosqlite
import pytest

from bot.db import Database, SlotTakenError


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "sub" / "test.db"))
    await database.init()
    return database


async def add(db, time="10:00", date="2026-10-01", user_id=1):
    return await db.add_lead(user_id, "Анна", "+79991234567", "Консультация", date, time)


async def test_add_and_get(db):
    lead_id = await add(db)
    lead = await db.get_lead(lead_id)
    assert lead["name"] == "Анна"
    assert lead["status"] == "new"


async def test_slot_cannot_be_taken_twice(db):
    await add(db)
    with pytest.raises(SlotTakenError):
        await add(db)


async def test_canceled_lead_frees_slot(db):
    lead_id = await add(db)
    await db.set_status(lead_id, "canceled")
    assert await db.booked_times("2026-10-01") == set()
    await add(db)  # слот снова доступен


async def test_booked_times(db):
    await add(db, "10:00")
    await add(db, "12:00")
    await add(db, "12:00", date="2026-10-02")
    assert await db.booked_times("2026-10-01") == {"10:00", "12:00"}


async def test_booked_between_groups_by_day(db):
    await add(db, "10:00")
    await add(db, "11:00", date="2026-10-02")
    await add(db, "11:00", date="2026-10-05")
    booked = await db.booked_between("2026-10-01", "2026-10-02")
    assert booked == {"2026-10-01": {"10:00"}, "2026-10-02": {"11:00"}}


async def test_list_leads_filter_and_limit(db):
    first = await add(db, "10:00")
    await add(db, "11:00")
    await add(db, "12:00")
    await db.set_status(first, "done")
    assert len(await db.list_leads(status="new")) == 2
    latest = await db.list_leads(limit=1)
    assert latest[0]["visit_time"] == "12:00"


async def test_leads_on_sorted_by_time(db):
    await add(db, "15:00")
    await add(db, "10:00")
    canceled = await add(db, "12:00")
    await db.set_status(canceled, "canceled")
    assert [lead["visit_time"] for lead in await db.leads_on("2026-10-01")] == ["10:00", "15:00"]


async def test_unknown_status_rejected(db):
    lead_id = await add(db)
    with pytest.raises(ValueError):
        await db.set_status(lead_id, "lost")


async def test_status_change_only_for_active(db):
    lead_id = await add(db)
    assert await db.set_status(lead_id, "confirmed")
    assert await db.set_status(lead_id, "done")
    # Выполненную заявку уже не отменить
    assert not await db.set_status(lead_id, "canceled")
    assert (await db.get_lead(lead_id))["status"] == "done"


async def test_client_cancels_only_own_lead(db):
    lead_id = await add(db)
    assert not await db.cancel_by_client(lead_id, user_id=2)
    assert await db.cancel_by_client(lead_id, user_id=1)
    lead = await db.get_lead(lead_id)
    assert lead["status"] == "canceled"
    assert lead["canceled_by"] == "client"


async def test_upcoming_skips_past_and_inactive(db):
    await add(db, "09:00")  # уже прошла
    future = await add(db, "15:00")
    other_day = await add(db, "10:00", date="2026-10-02")
    canceled = await add(db, "16:00")
    await db.set_status(canceled, "canceled")
    await add(db, "17:00", user_id=2)

    now = datetime(2026, 10, 1, 12, 0)
    assert [lead["id"] for lead in await db.upcoming(now, user_id=1)] == [future, other_day]
    assert len(await db.upcoming(now)) == 3
    assert await db.upcoming(now, user_id=3) == []


async def test_last_contact_and_reminder_flags(db):
    assert await db.last_contact(1) is None
    lead_id = await add(db)
    assert await db.last_contact(1) == {"name": "Анна", "phone": "+79991234567"}
    await db.mark_reminded(lead_id, "day")
    lead = await db.get_lead(lead_id)
    assert lead["reminded_day"] == 1
    assert lead["reminded_hours"] == 0


async def test_old_database_gets_new_columns(tmp_path):
    # База первой версии без колонок напоминаний должна обновиться при запуске
    path = str(tmp_path / "old.db")
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
            "user_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, service TEXT NOT NULL, "
            "visit_date TEXT NOT NULL, visit_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new')"
        )
        await conn.execute(
            "INSERT INTO leads (created_at, user_id, name, phone, service, visit_date, visit_time) "
            "VALUES ('2026-10-01 10:00', 1, 'Анна', '+79991234567', 'Стрижка', '2026-10-02', '10:00')"
        )
        await conn.commit()

    database = Database(path)
    await database.init()
    lead = await database.get_lead(1)
    assert lead["reminded_day"] == 0
    assert lead["canceled_by"] is None
