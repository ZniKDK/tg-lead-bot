"""Клавиатуры бота."""

from datetime import date

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Service
from bot.utils import format_date

remove = ReplyKeyboardRemove()


def services_kb(services: tuple[Service, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, service in enumerate(services):
        builder.button(text=service.label, callback_data=f"svc:{index}")
    builder.button(text="📋 Мои записи", callback_data="my")
    builder.adjust(1)
    return builder.as_markup()


def dates_kb(days: list[date]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in days:
        builder.button(text=format_date(day), callback_data=f"date:{day.isoformat()}")
    builder.button(text="⬅️ Назад", callback_data="back:service")
    builder.adjust(3)
    return builder.as_markup()


def times_kb(slots: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot, callback_data=f"time:{slot}")
    builder.button(text="⬅️ Назад", callback_data="back:date")
    builder.adjust(4)
    return builder.as_markup()


def name_kb(first_name: str | None) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """Кнопка с именем из профиля Telegram — чтобы не печатать его вручную."""
    if not first_name or not 2 <= len(first_name) <= 50:
        return remove
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=first_name)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_kb(can_edit_contact: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    if can_edit_contact:
        builder.button(text="✏️ Другие имя и телефон", callback_data="confirm:edit")
    builder.button(text="✖️ Отменить", callback_data="confirm:no")
    builder.adjust(1)
    return builder.as_markup()


def my_leads_kb(leads: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for lead in leads:
        builder.button(text=f"❌ Отменить №{lead['id']}", callback_data=f"mycancel:{lead['id']}")
    builder.button(text="➕ Новая запись", callback_data="new")
    builder.adjust(1)
    return builder.as_markup()


def cancel_ask_kb(lead_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, отменить", callback_data=f"mycancel_yes:{lead_id}")
    builder.button(text="Нет, оставить", callback_data="mycancel_no")
    return builder.as_markup()


def reminder_kb(lead_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить запись", callback_data=f"mycancel:{lead_id}")
    return builder.as_markup()


def lead_admin_kb(lead: dict) -> InlineKeyboardMarkup | None:
    """Кнопки зависят от статуса: новую подтверждают, подтверждённую отмечают выполненной."""
    builder = InlineKeyboardBuilder()
    if lead["status"] == "new":
        builder.button(text="📌 Подтвердить", callback_data=f"status:{lead['id']}:confirmed")
    elif lead["status"] == "confirmed":
        builder.button(text="✅ Выполнена", callback_data=f"status:{lead['id']}:done")
    else:
        return None
    builder.button(text="❌ Отменить", callback_data=f"status:{lead['id']}:canceled")
    return builder.as_markup()
