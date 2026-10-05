"""Команды администратора: расписание, заявки, смена статуса, выгрузка в CSV."""

import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.types import BufferedInputFile, CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import STATUSES, Database
from bot.utils import leads_to_csv

log = logging.getLogger(__name__)


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
        await message.answer(texts.lead_card(lead), reply_markup=kb.lead_admin_kb(lead))


@router.message(Command("help"))
async def admin_help(message: Message) -> None:
    await message.answer(texts.ADMIN_HELP)


@router.message(Command("today"))
async def today(message: Message, db: Database, settings: Settings) -> None:
    day = settings.now().date()
    await message.answer(texts.day_schedule(day, await db.leads_on(day.isoformat())))


@router.message(Command("tomorrow"))
async def tomorrow(message: Message, db: Database, settings: Settings) -> None:
    day = settings.now().date() + timedelta(days=1)
    await message.answer(texts.day_schedule(day, await db.leads_on(day.isoformat())))


@router.message(Command("leads"))
async def last_leads(message: Message, db: Database) -> None:
    await _send_leads(message, await db.list_leads(limit=10))


@router.message(Command("new"))
async def new_leads(message: Message, db: Database) -> None:
    await _send_leads(message, await db.list_leads(status="new"))


@router.message(Command("export"))
async def export(message: Message, db: Database, settings: Settings) -> None:
    leads = await db.list_leads()
    if not leads:
        await message.answer(texts.EMPTY)
        return
    filename = f"leads_{settings.now():%Y-%m-%d}.csv"
    await message.answer_document(
        BufferedInputFile(leads_to_csv(leads, STATUSES), filename=filename),
        caption=f"Всего заявок: {len(leads)}",
    )


@router.callback_query(F.data.startswith("status:"))
async def change_status(call: CallbackQuery, bot: Bot, db: Database, settings: Settings) -> None:
    _, lead_id, status = call.data.split(":")
    changed = await db.set_status(int(lead_id), status, canceled_by="admin" if status == "canceled" else None)
    lead = await db.get_lead(int(lead_id))
    # Карточку обновляем в любом случае: её могли закрыть с другого устройства или клиент отменил сам
    await call.message.edit_text(texts.lead_card(lead), reply_markup=kb.lead_admin_kb(lead))
    await call.answer(texts.STATUS_UPDATED if changed else texts.STATUS_STALE)
    if not changed:
        return

    notice = None
    if status == "confirmed":
        notice = texts.client_confirmed(lead, settings)
    elif status == "canceled":
        notice = texts.client_canceled(lead, settings)
    if notice:
        try:
            await bot.send_message(lead["user_id"], notice)
        except TelegramAPIError as error:
            # Клиент мог заблокировать бота — статус всё равно сохранён
            log.warning("Не удалось уведомить клиента по заявке %s: %s", lead_id, error)
