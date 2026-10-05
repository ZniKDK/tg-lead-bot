"""Сценарий записи клиента: услуга → дата → время → имя → телефон → подтверждение."""

import logging
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database, SlotTakenError
from bot.utils import available_dates, day_slots, format_date, normalize_phone

router = Router(name="client")
log = logging.getLogger(__name__)


class Booking(StatesGroup):
    service = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()


async def _show_dates(message: Message, state: FSMContext, settings: Settings) -> None:
    days = available_dates(date.today(), settings.days_ahead, settings.days_off)
    await state.set_state(Booking.date)
    if not days:
        await message.edit_text(texts.NO_DATES)
        return
    await message.edit_text(texts.CHOOSE_DATE, reply_markup=kb.dates_kb(days))


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await state.set_state(Booking.service)
    await message.answer(texts.START, reply_markup=kb.services_kb(settings.services))


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CANCELED, reply_markup=kb.remove)


@router.callback_query(Booking.service, F.data.startswith("svc:"))
async def pick_service(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    index = int(call.data.split(":")[1])
    await state.update_data(service=settings.services[index])
    await _show_dates(call.message, state, settings)
    await call.answer()


@router.callback_query(Booking.date, F.data == "back:service")
async def back_to_service(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.set_state(Booking.service)
    await call.message.edit_text(texts.START, reply_markup=kb.services_kb(settings.services))
    await call.answer()


@router.callback_query(Booking.date, F.data.startswith("date:"))
async def pick_date(call: CallbackQuery, state: FSMContext, settings: Settings, db: Database) -> None:
    day = date.fromisoformat(call.data.split(":", 1)[1])
    booked = await db.booked_times(day.isoformat())
    slots = day_slots(day, settings.work_start, settings.work_end, settings.slot_minutes, booked, datetime.now())
    if not slots:
        await call.answer(texts.NO_SLOTS, show_alert=True)
        return
    await state.update_data(date=day.isoformat(), date_label=format_date(day))
    await state.set_state(Booking.time)
    await call.message.edit_text(texts.CHOOSE_TIME.format(date=format_date(day)), reply_markup=kb.times_kb(slots))
    await call.answer()


@router.callback_query(Booking.time, F.data == "back:date")
async def back_to_date(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await _show_dates(call.message, state, settings)
    await call.answer()


@router.callback_query(Booking.time, F.data.startswith("time:"))
async def pick_time(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time=call.data.split(":", 1)[1])
    await state.set_state(Booking.name)
    await call.message.edit_text(texts.ASK_NAME)
    await call.answer()


@router.message(Booking.name, F.text)
async def get_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not 2 <= len(name) <= 50:
        await message.answer(texts.BAD_NAME)
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await message.answer(texts.ASK_PHONE, reply_markup=kb.phone_kb())


@router.message(Booking.phone, F.contact | F.text)
async def get_phone(message: Message, state: FSMContext) -> None:
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone:
        await message.answer(texts.BAD_PHONE)
        return
    await state.update_data(phone=phone)
    await state.set_state(Booking.confirm)
    # Убираем кнопку «Отправить номер» и показываем итог
    await message.answer("👌", reply_markup=kb.remove)
    await message.answer(texts.summary(await state.get_data()), reply_markup=kb.confirm_kb())


@router.callback_query(Booking.confirm, F.data == "confirm:no")
async def reject(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(texts.CANCELED)
    await call.answer()


@router.callback_query(Booking.confirm, F.data == "confirm:yes")
async def confirm(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    try:
        lead_id = await db.add_lead(
            user_id=call.from_user.id,
            name=data["name"],
            phone=data["phone"],
            service=data["service"],
            visit_date=data["date"],
            visit_time=data["time"],
        )
    except SlotTakenError:
        await call.answer(texts.SLOT_TAKEN, show_alert=True)
        await _show_dates(call.message, state, settings)
        return

    await state.clear()
    await call.message.edit_text(texts.DONE.format(id=lead_id))
    await call.answer()

    lead = await db.get_lead(lead_id)
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, texts.lead_card(lead), reply_markup=kb.lead_admin_kb(lead_id))
        except Exception:
            # Админ мог не запускать бота — заявка всё равно сохранена в базе
            log.exception("Не удалось уведомить админа %s", admin_id)


# Последний хендлер: ловит всё, что не подошло выше (текст вне записи, стикеры, фото,
# неизвестные команды), чтобы бот никогда не молчал
@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer(texts.FALLBACK_IDLE)
    elif current == Booking.name.state:
        await message.answer(texts.ASK_NAME)
    elif current == Booking.phone.state:
        await message.answer(texts.BAD_PHONE)
    else:
        await message.answer(texts.USE_BUTTONS)
