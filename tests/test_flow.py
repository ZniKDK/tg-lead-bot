"""Сквозной тест сценария записи: запросы к Telegram API перехватываются фейковой сессией."""

from datetime import date, datetime, time
from itertools import count

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User

from bot.config import Settings
from bot.db import Database
from bot.handlers import admin, client
from bot.utils import available_dates

CLIENT = User(id=100, is_bot=False, first_name="Анна")
ADMIN_ID = 999


class FakeSession(BaseSession):
    """Запоминает все вызовы API и возвращает правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        chat_id = getattr(method, "chat_id", None) or CLIENT.id
        return Message(message_id=1, date=datetime.now(), chat=Chat(id=chat_id, type="private"), text="ok")

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    def sent(self, name: str) -> list[TelegramMethod]:
        return [call for call in self.calls if type(call).__name__ == name]


class Harness:
    def __init__(self, db: Database, settings: Settings):
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.dp = Dispatcher(db=db, settings=settings)
        self.dp.include_routers(admin.router, client.router)
        self.ids = count(1)

    async def _feed(self, **payload):
        await self.dp.feed_update(self.bot, Update(update_id=next(self.ids), **payload))

    async def text(self, text: str, user: User = CLIENT):
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=next(self.ids), date=datetime.now(), chat=chat, from_user=user, text=text)
        await self._feed(message=message)

    async def contact(self, phone: str):
        chat = Chat(id=CLIENT.id, type="private")
        contact = Contact(phone_number=phone, first_name="Анна", user_id=CLIENT.id)
        message = Message(message_id=next(self.ids), date=datetime.now(), chat=chat, from_user=CLIENT, contact=contact)
        await self._feed(message=message)

    async def press(self, data: str, user: User = CLIENT):
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=1, date=datetime.now(), chat=chat, text="…")
        call = CallbackQuery(id=str(next(self.ids)), from_user=user, chat_instance="x", message=message, data=data)
        await self._feed(callback_query=call)


@pytest.fixture
async def harness(tmp_path):
    settings = Settings(
        bot_token="42:TEST",
        admin_ids=[ADMIN_ID],
        db_path=str(tmp_path / "leads.db"),
        work_start=time(0, 0),
        work_end=time(23, 59),
        days_ahead=7,
        days_off=(),
        services=["Консультация", "Ремонт"],
    )
    db = Database(settings.db_path)
    await db.init()
    h = Harness(db, settings)
    h.db = db
    yield h
    await h.bot.session.close()
    # Роутеры — объекты модуля: отвязываем их, чтобы следующий тест мог подключить заново
    for router in (admin.router, client.router):
        router._parent_router = None


def tomorrow() -> str:
    return available_dates(date.today(), 7, ())[1].isoformat()


async def book(h: Harness, slot: str = "12:00"):
    await h.text("/start")
    await h.press("svc:1")
    await h.press(f"date:{tomorrow()}")
    await h.press(f"time:{slot}")
    await h.text("Анна")
    await h.contact("89991234567")
    await h.press("confirm:yes")


async def test_full_booking_notifies_admin(harness):
    await book(harness)

    leads = await harness.db.list_leads()
    assert len(leads) == 1
    assert leads[0]["service"] == "Ремонт"
    assert leads[0]["phone"] == "+79991234567"
    assert leads[0]["visit_time"] == "12:00"

    to_admin = [m for m in harness.session.sent("SendMessage") if m.chat_id == ADMIN_ID]
    assert len(to_admin) == 1
    assert "Заявка №1" in to_admin[0].text


async def test_bad_phone_asks_again(harness):
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.press(f"date:{tomorrow()}")
    await harness.press("time:12:00")
    await harness.text("Анна")
    await harness.text("123")
    last = harness.session.sent("SendMessage")[-1]
    assert "Не получилось распознать номер" in last.text
    assert await harness.db.list_leads() == []


async def test_booked_slot_hidden_for_next_client(harness):
    await book(harness, "12:00")
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.press(f"date:{tomorrow()}")
    keyboard = harness.session.sent("EditMessageText")[-1].reply_markup
    buttons = [b.text for row in keyboard.inline_keyboard for b in row]
    assert "12:00" not in buttons
    assert "13:00" in buttons


async def test_admin_commands_only_for_admin(harness):
    await book(harness)
    admin_user = User(id=ADMIN_ID, is_bot=False, first_name="Админ")

    await harness.text("/export", user=admin_user)
    assert len(harness.session.sent("SendDocument")) == 1

    # Обычный пользователь выгрузку не получает
    await harness.text("/export")
    assert len(harness.session.sent("SendDocument")) == 1

    await harness.press("status:1:done", user=admin_user)
    assert (await harness.db.get_lead(1))["status"] == "done"


async def test_text_without_command_gets_hint(harness):
    await harness.text("Здравствуйте, сколько стоит ремонт?")
    last = harness.session.sent("SendMessage")[-1]
    assert "/start" in last.text


async def test_text_instead_of_buttons_gets_hint(harness):
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.text("завтра в 12")
    last = harness.session.sent("SendMessage")[-1]
    assert "кнопками" in last.text


async def test_admin_command_from_client_not_silent(harness):
    await harness.text("/export")
    assert harness.session.sent("SendDocument") == []
    assert "/start" in harness.session.sent("SendMessage")[-1].text
