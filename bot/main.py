"""Точка входа: python -m bot.main"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand

from bot import texts
from bot.config import load_settings
from bot.db import Database
from bot.handlers import admin, client


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    db = Database(settings.db_path)
    await db.init()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # db и settings автоматически передаются в хендлеры как аргументы
    dp = Dispatcher(db=db, settings=settings)
    # Админский роутер первым: его команды не должны перехватываться клиентским сценарием
    dp.include_routers(admin.router, client.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Записаться"),
        BotCommand(command="cancel", description="Отменить запись"),
        BotCommand(command="help", description="Помощь"),
    ])
    await notify_admins(bot, settings.admin_ids)
    await dp.start_polling(bot)


async def notify_admins(bot: Bot, admin_ids: list[int]) -> None:
    """Проверяем при запуске, что уведомления до админов доходят."""
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, texts.ADMIN_STARTED)
        except TelegramAPIError as error:
            # Обычная причина: админ ни разу не нажимал /start в этом боте или ID указан неверно
            logging.warning(
                "Админ %s не получит заявки: %s. Откройте бота с этого аккаунта и нажмите /start "
                "или проверьте ADMIN_IDS.",
                admin_id,
                error,
            )


if __name__ == "__main__":
    asyncio.run(main())
