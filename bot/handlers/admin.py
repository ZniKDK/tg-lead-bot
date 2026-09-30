"""Команды администратора: просмотр заявок, смена статуса, выгрузка в CSV."""

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import BufferedInputFile, CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database
from bot.utils import leads_to_csv


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _send_leads(message: Message, leads: list[dict]) -> None:
    if not leads:
        await message.answer(texts.EMPTY)
        return
    for lead in reversed(leads):
        markup = kb.lead_admin_kb(lead["id"]) if lead["status"] == "new" else None
        await message.answer(texts.lead_card(lead), reply_markup=markup)


@router.message(Command("leads"))
async def last_leads(message: Message, db: Database) -> None:
    await _send_leads(message, await db.list_leads(limit=10))


@router.message(Command("new"))
async def new_leads(message: Message, db: Database) -> None:
    await _send_leads(message, await db.list_leads(status="new"))


@router.message(Command("export"))
async def export(message: Message, db: Database) -> None:
    leads = await db.list_leads()
    if not leads:
        await message.answer(texts.EMPTY)
        return
    filename = f"leads_{datetime.now():%Y-%m-%d}.csv"
    await message.answer_document(
        BufferedInputFile(leads_to_csv(leads), filename=filename),
        caption=f"Всего заявок: {len(leads)}",
    )


@router.callback_query(F.data.startswith("status:"))
async def change_status(call: CallbackQuery, db: Database) -> None:
    _, lead_id, status = call.data.split(":")
    await db.set_status(int(lead_id), status)
    lead = await db.get_lead(int(lead_id))
    await call.message.edit_text(texts.lead_card(lead))
    await call.answer("Статус обновлён")
