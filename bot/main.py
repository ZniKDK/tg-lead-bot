"""Точка входа: python -m bot.main"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot import reminders, texts
from bot.config import ConfigError, load_settings
from bot.db import Database
from bot.handlers import admin, client

CLIENT_COMMANDS = [
    BotCommand(command="start", description="Записаться"),
    BotCommand(command="my", description="Мои записи"),
    BotCommand(command="cancel", description="Прервать запись"),
    BotCommand(command="help", description="Помощь"),
]
ADMIN_COMMANDS = [
    BotCommand(command="today", description="Расписание на сегодня"),
    BotCommand(command="tomorrow", description="Расписание на завтра"),
    BotCommand(command="new", description="Неподтверждённые заявки"),
    BotCommand(command="leads", description="Последние заявки"),
    BotCommand(command="export", description="Выгрузка в CSV"),
    BotCommand(command="start", description="Записаться (как клиент)"),
    BotCommand(command="help", description="Все команды"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as error:
        # Понятное сообщение вместо трассировки: владелец бота сразу видит, что поправить
        logging.error("%s", error)
        sys.exit(1)

    db = Database(settings.db_path)
    await db.init()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # db и settings автоматически передаются в хендлеры как аргументы
    dp = Dispatcher(db=db, settings=settings)
    # Админский роутер первым: его команды не должны перехватываться клиентским сценарием
    dp.include_routers(admin.router, client.router)

    await bot.set_my_commands(CLIENT_COMMANDS, scope=BotCommandScopeDefault())
    await setup_admins(bot, settings.admin_ids)

    reminder_task = asyncio.create_task(reminders.run(bot, db, settings))
    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()


async def setup_admins(bot: Bot, admin_ids: list[int]) -> None:
    """Админам — своё меню команд и сообщение «Бот запущен»: так видно, что уведомления доходят."""
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
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
