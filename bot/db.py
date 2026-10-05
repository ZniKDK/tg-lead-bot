"""Хранилище заявок на SQLite."""

import os
from datetime import datetime

import aiosqlite

STATUSES = {
    "new": "🆕 Новая",
    "confirmed": "📌 Подтверждена",
    "done": "✅ Выполнена",
    "canceled": "❌ Отменена",
}

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
CREATE INDEX IF NOT EXISTS ix_leads_user ON leads (user_id);
"""

# Колонки, добавленные после первой версии: базы старых установок дополняются при запуске
MIGRATIONS = {
    "reminded_day": "ALTER TABLE leads ADD COLUMN reminded_day INTEGER NOT NULL DEFAULT 0",
    "reminded_hours": "ALTER TABLE leads ADD COLUMN reminded_hours INTEGER NOT NULL DEFAULT 0",
    "canceled_by": "ALTER TABLE leads ADD COLUMN canceled_by TEXT",
}


class SlotTakenError(Exception):
    """Слот уже заняли, пока клиент заполнял форму."""


class Database:
    def __init__(self, path: str):
        self.path = path

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def init(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        async with self._connect() as conn:
            await conn.executescript(SCHEMA)
            cursor = await conn.execute("PRAGMA table_info(leads)")
            existing = {row[1] for row in await cursor.fetchall()}
            for column, statement in MIGRATIONS.items():
                if column not in existing:
                    await conn.execute(statement)
            await conn.commit()

    async def _fetch(self, query: str, params: tuple | list = ()) -> list[dict]:
        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, params)
            return [dict(row) for row in await cursor.fetchall()]

    async def add_lead(
        self,
        user_id: int,
        name: str,
        phone: str,
        service: str,
        visit_date: str,
        visit_time: str,
        created_at: datetime | None = None,
    ) -> int:
        # Время создания передаёт бот — в часовом поясе бизнеса, а не сервера
        created = (created_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
        try:
            async with self._connect() as conn:
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
        rows = await self._fetch(
            "SELECT visit_time FROM leads WHERE visit_date = ? AND status != 'canceled'", (visit_date,)
        )
        return {row["visit_time"] for row in rows}

    async def booked_between(self, date_from: str, date_to: str) -> dict[str, set[str]]:
        """Занятое время по дням за период (включительно) — одним запросом для всего календаря."""
        rows = await self._fetch(
            "SELECT visit_date, visit_time FROM leads WHERE visit_date BETWEEN ? AND ? AND status != 'canceled'",
            (date_from, date_to),
        )
        booked: dict[str, set[str]] = {}
        for row in rows:
            booked.setdefault(row["visit_date"], set()).add(row["visit_time"])
        return booked

    async def get_lead(self, lead_id: int) -> dict | None:
        rows = await self._fetch("SELECT * FROM leads WHERE id = ?", (lead_id,))
        return rows[0] if rows else None

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
        return await self._fetch(query, params)

    async def leads_on(self, visit_date: str) -> list[dict]:
        """Расписание дня: все неотменённые записи по времени."""
        return await self._fetch(
            "SELECT * FROM leads WHERE visit_date = ? AND status != 'canceled' ORDER BY visit_time",
            (visit_date,),
        )

    async def upcoming(self, now: datetime, user_id: int | None = None) -> list[dict]:
        """Активные записи, время которых ещё не наступило. Без user_id — по всем клиентам."""
        query = "SELECT * FROM leads WHERE status IN ('new', 'confirmed') AND visit_date || ' ' || visit_time > ?"
        params: list = [now.strftime("%Y-%m-%d %H:%M")]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY visit_date, visit_time"
        return await self._fetch(query, params)

    async def last_contact(self, user_id: int) -> dict | None:
        """Имя и телефон из прошлой заявки — постоянному клиенту не нужно вводить их снова."""
        rows = await self._fetch("SELECT name, phone FROM leads WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        return rows[0] if rows else None

    async def set_status(self, lead_id: int, status: str, canceled_by: str | None = None) -> bool:
        """Меняет статус активной заявки. Выполненную или отменённую повторно не трогаем."""
        if status not in STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        async with self._connect() as conn:
            cursor = await conn.execute(
                "UPDATE leads SET status = ?, canceled_by = ? WHERE id = ? AND status IN ('new', 'confirmed')",
                (status, canceled_by, lead_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def cancel_by_client(self, lead_id: int, user_id: int) -> bool:
        """Клиент отменяет только свою активную запись."""
        async with self._connect() as conn:
            cursor = await conn.execute(
                "UPDATE leads SET status = 'canceled', canceled_by = 'client' "
                "WHERE id = ? AND user_id = ? AND status IN ('new', 'confirmed')",
                (lead_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def mark_reminded(self, lead_id: int, kind: str) -> None:
        column = {"day": "reminded_day", "hours": "reminded_hours"}[kind]
        async with self._connect() as conn:
            await conn.execute(f"UPDATE leads SET {column} = 1 WHERE id = ?", (lead_id,))
            await conn.commit()
