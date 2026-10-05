"""Клиентская часть: запись (услуга → дата → время → имя → телефон → подтверждение) и «Мои записи»."""

import logging
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database, SlotTakenError
from bot.utils import day_slots, format_date_long, normalize_phone, visit_datetime, working_days

router = Router(name="client")
log = logging.getLogger(__name__)


class Booking(StatesGroup):
    service = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()


async def free_days(db: Database, settings: Settings) -> dict[date, list[str]]:
    """Дни, в которых осталось хотя бы одно свободное время, и сами слоты."""
    now = settings.now()
    earliest = now + timedelta(minutes=settings.min_minutes_before)
    days = working_days(now.date(), settings.days_ahead, settings.schedule, settings.holidays)
    if not days:
        return {}
    booked = await db.booked_between(days[0].isoformat(), days[-1].isoformat())
    result = {}
    for day in days:
        slots = day_slots(
            day, settings.schedule[day.weekday()], settings.slot_minutes, booked.get(day.isoformat(), set()), earliest
        )
        if slots:
            result[day] = slots
    return result


async def _show_dates(message: Message, state: FSMContext, settings: Settings, db: Database) -> None:
    days = await free_days(db, settings)
    data = await state.get_data()
    await state.set_state(Booking.date)
    if not days:
        await message.edit_text(texts.NO_DATES)
        return
    markup = kb.dates_kb(list(days), settings.now().date())
    await message.edit_text(texts.CHOOSE_DATE.format(service=data["service"]), reply_markup=markup)


async def _limit_reached(user_id: int, db: Database, settings: Settings) -> bool:
    active = await db.upcoming(settings.now(), user_id=user_id)
    return len(active) >= settings.max_active_per_user


async def _notify_admins(bot: Bot, settings: Settings, text: str, reply_markup=None) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            # Админ мог не запускать бота — заявка всё равно сохранена в базе
            log.exception("Не удалось уведомить админа %s", admin_id)


async def _ask_name(call: CallbackQuery) -> None:
    await call.message.edit_text(texts.ASK_NAME)
    markup = kb.name_kb(call.from_user.first_name)
    if markup is not kb.remove:
        # Кнопка с именем из профиля: клиенту достаточно нажать, а не печатать
        await call.message.answer(texts.NAME_HINT, reply_markup=markup)


# --- Начало и справка ---


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await state.set_state(Booking.service)
    await message.answer(texts.start(settings), reply_markup=kb.services_kb(settings.services))


@router.callback_query(F.data == "new")
async def start_again(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await state.set_state(Booking.service)
    await call.message.edit_text(texts.start(settings), reply_markup=kb.services_kb(settings.services))
    await call.answer()


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(texts.CLIENT_HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CANCELED, reply_markup=kb.remove)


# --- Сценарий записи ---


@router.callback_query(Booking.service, F.data.startswith("svc:"))
async def pick_service(call: CallbackQuery, state: FSMContext, settings: Settings, db: Database) -> None:
    index = int(call.data.split(":")[1])
    if index >= len(settings.services):
        # Кнопка от старого списка услуг, который владелец уже поменял
        await call.message.edit_text(texts.start(settings), reply_markup=kb.services_kb(settings.services))
        await call.answer()
        return
    if await _limit_reached(call.from_user.id, db, settings):
        await call.answer(texts.LIMIT_REACHED.format(count=settings.max_active_per_user), show_alert=True)
        return
    await state.update_data(service=settings.services[index].name)
    await _show_dates(call.message, state, settings, db)
    await call.answer()


@router.callback_query(Booking.date, F.data == "back:service")
async def back_to_service(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.set_state(Booking.service)
    await call.message.edit_text(texts.start(settings), reply_markup=kb.services_kb(settings.services))
    await call.answer()


@router.callback_query(Booking.date, F.data.startswith("date:"))
async def pick_date(call: CallbackQuery, state: FSMContext, settings: Settings, db: Database) -> None:
    day = date.fromisoformat(call.data.split(":", 1)[1])
    # Пересчитываем слоты: пока клиент думал, время могли занять
    slots = (await free_days(db, settings)).get(day)
    if not slots:
        await call.answer(texts.NO_SLOTS, show_alert=True)
        await _show_dates(call.message, state, settings, db)
        return
    data = await state.get_data()
    await state.update_data(date=day.isoformat(), date_label=format_date_long(day))
    await state.set_state(Booking.time)
    await call.message.edit_text(
        texts.CHOOSE_TIME.format(service=data["service"], date=format_date_long(day)), reply_markup=kb.times_kb(slots)
    )
    await call.answer()


@router.callback_query(Booking.time, F.data == "back:date")
async def back_to_date(call: CallbackQuery, state: FSMContext, settings: Settings, db: Database) -> None:
    await _show_dates(call.message, state, settings, db)
    await call.answer()


@router.callback_query(Booking.time, F.data.startswith("time:"))
async def pick_time(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.update_data(time=call.data.split(":", 1)[1])
    await call.answer()

    # Постоянный клиент: подставляем имя и телефон из прошлой заявки и сразу показываем итог
    contact = await db.last_contact(call.from_user.id)
    if contact:
        await state.update_data(name=contact["name"], phone=contact["phone"])
        await state.set_state(Booking.confirm)
        await call.message.edit_text(texts.summary(await state.get_data()), reply_markup=kb.confirm_kb(True))
        return

    await state.set_state(Booking.name)
    await _ask_name(call)


@router.callback_query(Booking.confirm, F.data == "confirm:edit")
async def edit_contact(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Booking.name)
    await _ask_name(call)
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
    await message.answer("Спасибо! 👌", reply_markup=kb.remove)
    await message.answer(texts.summary(await state.get_data()), reply_markup=kb.confirm_kb())


@router.callback_query(Booking.confirm, F.data == "confirm:no")
async def reject(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(texts.CANCELED)
    await call.answer()


@router.callback_query(Booking.confirm, F.data == "confirm:yes")
async def confirm(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database, settings: Settings) -> None:
    if await _limit_reached(call.from_user.id, db, settings):
        await state.clear()
        await call.message.edit_text(texts.LIMIT_REACHED.format(count=settings.max_active_per_user))
        await call.answer()
        return

    data = await state.get_data()
    try:
        lead_id = await db.add_lead(
            user_id=call.from_user.id,
            name=data["name"],
            phone=data["phone"],
            service=data["service"],
            visit_date=data["date"],
            visit_time=data["time"],
            created_at=settings.now(),
        )
    except SlotTakenError:
        await call.answer(texts.SLOT_TAKEN, show_alert=True)
        await _show_dates(call.message, state, settings, db)
        return

    await state.clear()
    lead = await db.get_lead(lead_id)
    await call.message.edit_text(texts.done(lead, settings))
    await call.answer()
    await _notify_admins(bot, settings, texts.lead_card(lead), kb.lead_admin_kb(lead))


# --- Мои записи и отмена клиентом ---


async def _my_leads(user_id: int, db: Database, settings: Settings) -> tuple[str, object]:
    leads = await db.upcoming(settings.now(), user_id=user_id)
    if not leads:
        return texts.NO_UPCOMING, None
    lines = [texts.MY_TITLE, ""]
    lines += [f"№{lead['id']} {texts.visit_line(lead)}" for lead in leads]
    return "\n".join(lines), kb.my_leads_kb(leads)


@router.message(Command("my"))
async def my_cmd(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    text, markup = await _my_leads(message.from_user.id, db, settings)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "my")
async def my_button(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.clear()
    text, markup = await _my_leads(call.from_user.id, db, settings)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


async def _cancellable(call: CallbackQuery, lead_id: int, db: Database, settings: Settings) -> dict | None:
    """Своя ли это запись, активна ли она и не поздно ли её отменять. Иначе объясняем клиенту."""
    lead = await db.get_lead(lead_id)
    if not lead or lead["user_id"] != call.from_user.id or lead["status"] not in ("new", "confirmed"):
        await call.answer(texts.CANCEL_GONE, show_alert=True)
        return None
    if visit_datetime(lead) - settings.now() < timedelta(hours=settings.cancel_hours_before):
        await call.answer(texts.cancel_too_late(settings), show_alert=True)
        return None
    return lead


@router.callback_query(F.data.startswith("mycancel:"))
async def cancel_ask(call: CallbackQuery, db: Database, settings: Settings) -> None:
    lead = await _cancellable(call, int(call.data.split(":")[1]), db, settings)
    if lead:
        await call.message.edit_text(
            texts.CANCEL_ASK.format(lead=texts.visit_line(lead)), reply_markup=kb.cancel_ask_kb(lead["id"])
        )
        await call.answer()


@router.callback_query(F.data.startswith("mycancel_yes:"))
async def cancel_yes(call: CallbackQuery, bot: Bot, db: Database, settings: Settings) -> None:
    lead = await _cancellable(call, int(call.data.split(":")[1]), db, settings)
    if not lead or not await db.cancel_by_client(lead["id"], call.from_user.id):
        return
    await call.message.edit_text(texts.CANCEL_DONE)
    await call.answer()
    await _notify_admins(bot, settings, texts.client_canceled_for_admin(await db.get_lead(lead["id"])))


@router.callback_query(F.data == "mycancel_no")
async def cancel_no(call: CallbackQuery) -> None:
    await call.message.edit_text(texts.CANCEL_KEPT)
    await call.answer()


# --- Всё остальное ---


@router.callback_query()
async def stale_button(call: CallbackQuery) -> None:
    """Кнопка из старого сообщения (например, после перезапуска бота) — не оставляем «часики»."""
    await call.answer("Эта кнопка устарела. Начните заново — /start", show_alert=True)


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
