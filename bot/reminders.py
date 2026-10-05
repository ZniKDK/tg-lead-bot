"""Фоновая отправка напоминаний клиентам перед визитом."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database
from bot.utils import reminders_due

log = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 60


async def send_due(bot: Bot, db: Database, settings: Settings) -> int:
    """Один проход: отправляет все напоминания, которым пришло время. Возвращает их число."""
    now = settings.now()
    due = reminders_due(await db.upcoming(now), now, settings.remind_day_before, settings.remind_hours_before)
    sent = 0
    for lead, kind in due:
        try:
            await bot.send_message(
                lead["user_id"], texts.reminder(lead, kind, settings), reply_markup=kb.reminder_kb(lead["id"])
            )
            sent += 1
        except TelegramForbiddenError:
            # Клиент заблокировал бота — повторять бессмысленно
            log.info("Клиент по заявке %s заблокировал бота, напоминание пропущено", lead["id"])
        except TelegramAPIError as error:
            # Временный сбой сети или Telegram — попробуем на следующем проходе
            log.warning("Напоминание по заявке %s не отправлено: %s", lead["id"], error)
            continue
        await db.mark_reminded(lead["id"], kind)
    return sent


async def run(bot: Bot, db: Database, settings: Settings) -> None:
    """Бесконечный цикл проверки. Ошибка одного прохода не останавливает бота."""
    if not settings.remind_day_before and not settings.remind_hours_before:
        return
    while True:
        try:
            await send_due(bot, db, settings)
        except Exception:
            log.exception("Сбой при отправке напоминаний")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
