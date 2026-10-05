"""Сквозные тесты сценариев: запросы к Telegram API перехватываются фейковой сессией."""

from datetime import datetime, time, timedelta
from itertools import count

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User

from bot import reminders
from bot.config import Service, Settings
from bot.db import Database
from bot.handlers import admin, client

CLIENT = User(id=100, is_bot=False, first_name="Анна")
OTHER = User(id=200, is_bot=False, first_name="Борис")
ADMIN = User(id=999, is_bot=False, first_name="Админ")


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

    def messages_to(self, chat_id: int) -> list[str]:
        return [call.text for call in self.sent("SendMessage") if call.chat_id == chat_id]

    def last_text(self) -> str:
        """Последний текст, который увидел пользователь: новое сообщение или правка старого."""
        texts = [call for call in self.calls if type(call).__name__ in ("SendMessage", "EditMessageText")]
        return texts[-1].text

    def alerts(self) -> list[str]:
        return [call.text for call in self.sent("AnswerCallbackQuery") if call.text]


class Harness:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
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

    async def contact(self, phone: str, user: User = CLIENT):
        chat = Chat(id=user.id, type="private")
        contact = Contact(phone_number=phone, first_name=user.first_name, user_id=user.id)
        message = Message(message_id=next(self.ids), date=datetime.now(), chat=chat, from_user=user, contact=contact)
        await self._feed(message=message)

    async def press(self, data: str, user: User = CLIENT):
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=1, date=datetime.now(), chat=chat, text="…")
        call = CallbackQuery(id=str(next(self.ids)), from_user=user, chat_instance="x", message=message, data=data)
        await self._feed(callback_query=call)

    def buttons(self) -> list[str]:
        markup = self.session.sent("EditMessageText")[-1].reply_markup
        return [button.text for row in markup.inline_keyboard for button in row]


@pytest.fixture
async def harness(tmp_path):
    settings = Settings(
        bot_token="42:TEST",
        admin_ids=[ADMIN.id],
        db_path=str(tmp_path / "leads.db"),
        business_name="Барбершоп «Бритва»",
        address="ул. Примерная, 1",
        phone="+7 999 000-00-00",
        services=(Service("Консультация"), Service("Ремонт", "2 000 ₽")),
        # Работаем круглосуточно без выходных — тесты не зависят от дня и часа запуска
        schedule={day: ((time(0, 0), time(23, 59)),) for day in range(7)},
        min_minutes_before=0,
    )
    db = Database(settings.db_path)
    await db.init()
    h = Harness(db, settings)
    yield h
    await h.bot.session.close()
    # Роутеры — объекты модуля: отвязываем их, чтобы следующий тест мог подключить заново
    for router in (admin.router, client.router):
        router._parent_router = None


def tomorrow(h: Harness) -> str:
    return (h.settings.now().date() + timedelta(days=1)).isoformat()


async def book(h: Harness, slot: str = "12:00", user: User = CLIENT, day: str | None = None):
    await h.text("/start", user=user)
    await h.press("svc:1", user=user)
    await h.press(f"date:{day or tomorrow(h)}", user=user)
    await h.press(f"time:{slot}", user=user)
    if await h.db.last_contact(user.id) is None:
        await h.text(user.first_name, user=user)
        await h.contact("89991234567", user=user)
    await h.press("confirm:yes", user=user)


# --- Запись ---


async def test_full_booking_notifies_admin(harness):
    await book(harness)

    leads = await harness.db.list_leads()
    assert len(leads) == 1
    assert leads[0]["service"] == "Ремонт"
    assert leads[0]["phone"] == "+79991234567"
    assert leads[0]["visit_time"] == "12:00"
    assert "Заявка №1 принята" in harness.session.sent("EditMessageText")[-1].text

    to_admin = harness.session.messages_to(ADMIN.id)
    assert len(to_admin) == 1
    assert "Заявка №1" in to_admin[0]
    assert "+7 999 123-45-67" in to_admin[0]


async def test_start_shows_business_and_prices(harness):
    await harness.text("/start")
    message = harness.session.sent("SendMessage")[-1]
    assert "Барбершоп «Бритва»" in message.text
    buttons = [button.text for row in message.reply_markup.inline_keyboard for button in row]
    assert buttons == ["Консультация", "Ремонт · 2 000 ₽", "📋 Мои записи"]


async def test_name_button_from_telegram_profile(harness):
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.press(f"date:{tomorrow(harness)}")
    await harness.press("time:12:00")
    keyboard = harness.session.sent("SendMessage")[-1].reply_markup
    assert keyboard.keyboard[0][0].text == "Анна"


async def test_bad_phone_asks_again(harness):
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.press(f"date:{tomorrow(harness)}")
    await harness.press("time:12:00")
    await harness.text("Анна")
    await harness.text("123")
    assert "Не получилось распознать номер" in harness.session.last_text()
    assert await harness.db.list_leads() == []


async def test_booked_slot_hidden_for_next_client(harness):
    await book(harness, "12:00")
    await harness.text("/start", user=OTHER)
    await harness.press("svc:0", user=OTHER)
    await harness.press(f"date:{tomorrow(harness)}", user=OTHER)
    assert "12:00" not in harness.buttons()
    assert "13:00" in harness.buttons()


async def test_returning_client_skips_name_and_phone(harness):
    await book(harness, "12:00")
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.press(f"date:{tomorrow(harness)}")
    await harness.press("time:14:00")
    # Сразу итог с данными из прошлой заявки и кнопкой «изменить»
    assert "Проверьте данные" in harness.session.last_text()
    assert "✏️ Другие имя и телефон" in harness.buttons()
    await harness.press("confirm:yes")
    assert len(await harness.db.list_leads()) == 2


async def test_active_bookings_limit(harness):
    await book(harness, "12:00")
    await book(harness, "13:00")
    await harness.text("/start")
    await harness.press("svc:0")
    assert "не больше 2" in harness.session.alerts()[-1]
    assert len(await harness.db.list_leads()) == 2


async def test_text_instead_of_buttons_gets_hint(harness):
    await harness.text("/start")
    await harness.press("svc:0")
    await harness.text("завтра в 12")
    assert "кнопками" in harness.session.last_text()


async def test_text_without_command_gets_hint(harness):
    await harness.text("Здравствуйте, сколько стоит ремонт?")
    assert "/start" in harness.session.last_text()


async def test_stale_button_answered(harness):
    # Кнопка выбора времени без начатой записи — например, после перезапуска бота
    await harness.press("time:12:00")
    assert "устарела" in harness.session.alerts()[-1]


# --- Мои записи ---


async def test_client_cancels_own_booking(harness):
    await book(harness)
    await harness.text("/my")
    assert "Ваши записи" in harness.session.last_text()

    await harness.press("mycancel:1")
    assert "Отменить запись?" in harness.session.last_text()
    await harness.press("mycancel_yes:1")

    lead = await harness.db.get_lead(1)
    assert lead["status"] == "canceled"
    assert "Клиент отменил запись" in harness.session.messages_to(ADMIN.id)[-1]


async def test_cannot_cancel_foreign_booking(harness):
    await book(harness)
    await harness.press("mycancel_yes:1", user=OTHER)
    assert (await harness.db.get_lead(1))["status"] == "new"
    assert "неактивна" in harness.session.alerts()[-1]


async def test_cannot_cancel_right_before_visit(harness):
    soon = harness.settings.now() + timedelta(hours=1)
    lead_id = await harness.db.add_lead(
        CLIENT.id, "Анна", "+79991234567", "Ремонт", soon.date().isoformat(), soon.strftime("%H:%M")
    )
    await harness.press(f"mycancel:{lead_id}")
    assert "только по телефону +7 999 000-00-00" in harness.session.alerts()[-1]
    assert (await harness.db.get_lead(lead_id))["status"] == "new"


async def test_my_without_bookings(harness):
    await harness.text("/my")
    assert "нет предстоящих записей" in harness.session.last_text()


# --- Администратор ---


async def test_admin_confirms_and_client_is_notified(harness):
    await book(harness)
    await harness.press("status:1:confirmed", user=ADMIN)
    assert (await harness.db.get_lead(1))["status"] == "confirmed"
    assert "запись подтверждена" in harness.session.messages_to(CLIENT.id)[-1]
    # У подтверждённой заявки следующая кнопка — «Выполнена»
    assert harness.buttons() == ["✅ Выполнена", "❌ Отменить"]

    await harness.press("status:1:done", user=ADMIN)
    assert (await harness.db.get_lead(1))["status"] == "done"


async def test_admin_cancel_notifies_client(harness):
    await book(harness)
    await harness.press("status:1:canceled", user=ADMIN)
    assert "пришлось отменить" in harness.session.messages_to(CLIENT.id)[-1]


async def test_closed_lead_not_changed_twice(harness):
    await book(harness)
    await harness.press("mycancel_yes:1")
    await harness.press("status:1:confirmed", user=ADMIN)
    assert (await harness.db.get_lead(1))["status"] == "canceled"
    assert harness.session.alerts()[-1] == "Заявка уже закрыта"


async def test_admin_commands_only_for_admin(harness):
    await book(harness)
    await harness.text("/export", user=ADMIN)
    assert len(harness.session.sent("SendDocument")) == 1

    # Обычный пользователь выгрузку не получает, но и без ответа не остаётся
    await harness.text("/export")
    assert len(harness.session.sent("SendDocument")) == 1
    assert "/start" in harness.session.last_text()

    await harness.press("status:1:done")
    assert (await harness.db.get_lead(1))["status"] == "new"


async def test_help_differs_for_admin_and_client(harness):
    await harness.text("/help")
    assert "/export" not in harness.session.last_text()
    await harness.text("/help", user=ADMIN)
    assert "/export" in harness.session.last_text()


async def test_schedule_for_tomorrow(harness):
    await book(harness, "15:00")
    await book(harness, "11:00", user=OTHER)
    await harness.text("/tomorrow", user=ADMIN)
    schedule = harness.session.last_text()
    assert schedule.index("11:00") < schedule.index("15:00")
    assert "Борис" in schedule


# --- Напоминания ---


async def test_reminder_sent_once(harness):
    now = harness.settings.now()
    visit = now + timedelta(hours=23)
    lead_id = await harness.db.add_lead(
        CLIENT.id,
        "Анна",
        "+79991234567",
        "Ремонт",
        visit.date().isoformat(),
        visit.strftime("%H:%M"),
        created_at=now - timedelta(days=2),
    )

    assert await reminders.send_due(harness.bot, harness.db, harness.settings) == 1
    reminder = harness.session.sent("SendMessage")[-1]
    assert reminder.chat_id == CLIENT.id
    assert "Завтра у вас запись" in reminder.text
    assert reminder.reply_markup.inline_keyboard[0][0].callback_data == f"mycancel:{lead_id}"

    # Повторно то же напоминание не уходит
    assert await reminders.send_due(harness.bot, harness.db, harness.settings) == 0
