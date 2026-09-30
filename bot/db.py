"""Хранилище заявок на SQLite."""

import os
from datetime import datetime

import aiosqlite

STATUSES = {"new": "🆕 Новая", "done": "✅ Выполнена", "canceled": "❌ Отменена"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL,
    service     TEXT NOT NULL,
    visit_date  TEXT NOT NULL,
    visit_time  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new'
);
-- Один слот нельзя занять дважды (отменённые заявки слот освобождают)
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_slot
    ON leads (visit_date, visit_time) WHERE status != 'canceled';
"""


class SlotTakenError(Exception):
    """Слот уже заняли, пока клиент заполнял форму."""


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()

    async def add_lead(
        self, user_id: int, name: str, phone: str, service: str, visit_date: str, visit_time: str
    ) -> int:
        created = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            async with aiosqlite.connect(self.path) as conn:
                cursor = await conn.execute(
                    "INSERT INTO leads (created_at, user_id, name, phone, service, visit_date, visit_time) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (created, user_id, name, phone, service, visit_date, visit_time),
                )
                await conn.commit()
                return cursor.lastrowid
        except aiosqlite.IntegrityError as error:
            raise SlotTakenError from error

    async def booked_times(self, visit_date: str) -> set[str]:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "SELECT visit_time FROM leads WHERE visit_date = ? AND status != 'canceled'",
                (visit_date,),
            )
            return {row[0] for row in await cursor.fetchall()}

    async def get_lead(self, lead_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_leads(self, status: str | None = None, limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM leads"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, params)
            return [dict(row) for row in await cursor.fetchall()]

    async def set_status(self, lead_id: int, status: str) -> bool:
        if status not in STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
            await conn.commit()
            return cursor.rowcount > 0
