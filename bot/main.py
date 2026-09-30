"""Точка входа: python -m bot.main"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
