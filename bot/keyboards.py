"""Клавиатуры бота."""

from datetime import date

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils import format_date

remove = ReplyKeyboardRemove()


def services_kb(services: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, name in enumerate(services):
        builder.button(text=name, callback_data=f"svc:{index}")
    builder.adjust(1)
    return builder.as_markup()


def dates_kb(days: list[date]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in days:
        builder.button(text=format_date(day), callback_data=f"date:{day.isoformat()}")
    builder.button(text="⬅️ Назад", callback_data="back:service")
    builder.adjust(2)
    return builder.as_markup()


def times_kb(slots: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot, callback_data=f"time:{slot}")
    builder.button(text="⬅️ Назад", callback_data="back:date")
    builder.adjust(4)
    return builder.as_markup()


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    builder.button(text="✖️ Отменить", callback_data="confirm:no")
    return builder.as_markup()


def lead_admin_kb(lead_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Выполнена", callback_data=f"status:{lead_id}:done")
    builder.button(text="❌ Отменить", callback_data=f"status:{lead_id}:canceled")
    return builder.as_markup()
