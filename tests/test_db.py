import pytest

from bot.db import Database, SlotTakenError


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "sub" / "test.db"))
    await database.init()
    return database


async def add(db, time="10:00", date="2026-10-01"):
    return await db.add_lead(1, "Анна", "+79991234567", "Консультация", date, time)


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


async def test_list_leads_filter_and_limit(db):
    first = await add(db, "10:00")
    await add(db, "11:00")
    await add(db, "12:00")
    await db.set_status(first, "done")
    assert len(await db.list_leads(status="new")) == 2
    latest = await db.list_leads(limit=1)
    assert latest[0]["visit_time"] == "12:00"


async def test_unknown_status_rejected(db):
    lead_id = await add(db)
    with pytest.raises(ValueError):
        await db.set_status(lead_id, "lost")
