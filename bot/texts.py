"""Тексты сообщений. Вынесены отдельно, чтобы заказчик мог править их без погружения в код."""

from datetime import date
from html import escape

from bot.config import Settings
from bot.db import STATUSES
from bot.utils import format_created, format_date_long, format_phone

CLIENT_HELP = (
    "<b>Что умеет бот</b>\n\n"
    "/start — записаться\n"
    "/my — мои записи: посмотреть или отменить\n"
    "/cancel — прервать запись, если передумали\n\n"
    "Перед визитом я пришлю напоминание."
)
ADMIN_HELP = (
    "<b>Команды администратора</b>\n\n"
    "/today — расписание на сегодня\n"
    "/tomorrow — расписание на завтра\n"
    "/new — неподтверждённые заявки\n"
    "/leads — последние 10 заявок\n"
    "/export — все заявки в CSV для Excel\n\n"
    "Клиентская часть: /start, /my."
)
CHOOSE_SERVICE = "Выберите услугу:"
CHOOSE_DATE = "<b>{service}</b>\n\nВыберите удобный день:"
CHOOSE_TIME = "<b>{service}</b> · {date}\n\nСвободное время:"
NO_SLOTS = "На этот день время уже разобрали, выберите другой."
NO_DATES = "Сейчас нет свободного времени для записи. Попробуйте позже или позвоните нам."
ASK_NAME = "Как к вам обращаться?"
NAME_HINT = "Напишите имя или нажмите кнопку 👇"
ASK_PHONE = "Оставьте номер телефона: нажмите кнопку ниже или напишите его сообщением."
BAD_NAME = "Имя должно быть от 2 до 50 символов. Попробуйте ещё раз."
BAD_PHONE = "Не получилось распознать номер. Пример: +7 999 123-45-67"
CANCELED = "Хорошо, запись не создана. Чтобы начать заново — /start"
SLOT_TAKEN = "Увы, это время только что заняли. Выберите другое 🙏"
LIMIT_REACHED = "Можно иметь не больше {count} активных записей одновременно. Посмотреть или отменить их — /my"
EMPTY = "Заявок пока нет."
NO_UPCOMING = "У вас нет предстоящих записей. Записаться — /start"
MY_TITLE = "<b>Ваши записи</b>"
CANCEL_ASK = "Отменить запись?\n\n{lead}"
CANCEL_DONE = "Запись отменена. Будем рады видеть вас в другой раз — /start"
CANCEL_KEPT = "Отлично, запись остаётся в силе 👍"
CANCEL_TOO_LATE = "До визита меньше {hours} ч — отменить запись можно только по телефону{phone}."
CANCEL_GONE = "Эта запись уже неактивна."
FALLBACK_IDLE = "Я принимаю записи на услуги.\n\n/start — записаться\n/my — мои записи"
USE_BUTTONS = "Пожалуйста, воспользуйтесь кнопками выше 👆 или /cancel, чтобы начать заново."
ADMIN_STARTED = "✅ Бот запущен. Новые заявки будут приходить сюда. Команды — /help"
STATUS_UPDATED = "Статус обновлён"
STATUS_STALE = "Заявка уже закрыта"

# Сообщения клиенту при действиях администратора
CLIENT_CONFIRMED = "✅ Ваша запись подтверждена!\n\n{lead}\n\nЖдём вас{address}."
CLIENT_CANCELED_BY_ADMIN = "К сожалению, запись пришлось отменить:\n\n{lead}\n\nВыберите другое время — /start{phone}"


def start(settings: Settings) -> str:
    lines = [f"Здравствуйте! 👋 Это бот записи <b>{escape(settings.business_name)}</b>."]
    if settings.address:
        lines.append(f"📍 {escape(settings.address)}")
    lines.append("\nЗапишитесь за минуту — выберите услугу:")
    return "\n".join(lines)


def visit_line(lead: dict) -> str:
    """«🗓 чт, 9 октября, 16:00 · Стрижка»."""
    day = date.fromisoformat(lead["visit_date"])
    return f"🗓 <b>{format_date_long(day)}, {lead['visit_time']}</b> · {escape(lead['service'])}"


def summary(data: dict) -> str:
    return (
        "<b>Проверьте данные</b>\n\n"
        f"Услуга: <b>{escape(data['service'])}</b>\n"
        f"Когда: <b>{data['date_label']}, {data['time']}</b>\n"
        f"Имя: <b>{escape(data['name'])}</b>\n"
        f"Телефон: <b>{format_phone(data['phone'])}</b>"
    )


def done(lead: dict, settings: Settings) -> str:
    text = (
        f"Готово! Заявка №{lead['id']} принята 🙌\n\n{visit_line(lead)}\n\n"
        "Мы подтвердим запись в ближайшее время. Перед визитом пришлю напоминание."
    )
    if settings.address:
        text += f"\n\n📍 {escape(settings.address)}"
    return text


def _phone_suffix(settings: Settings, prefix: str) -> str:
    return f"{prefix}{escape(settings.phone)}" if settings.phone else ""


def cancel_too_late(settings: Settings) -> str:
    return CANCEL_TOO_LATE.format(hours=settings.cancel_hours_before, phone=_phone_suffix(settings, " "))


def client_confirmed(lead: dict, settings: Settings) -> str:
    address = f" по адресу: {escape(settings.address)}" if settings.address else ""
    return CLIENT_CONFIRMED.format(lead=visit_line(lead), address=address)


def client_canceled(lead: dict, settings: Settings) -> str:
    return CLIENT_CANCELED_BY_ADMIN.format(lead=visit_line(lead), phone=_phone_suffix(settings, "\nили позвоните: "))


def reminder(lead: dict, kind: str, settings: Settings) -> str:
    when = "Завтра" if kind == "day" else "Скоро"
    text = f"⏰ <b>{when} у вас запись</b>\n\n{visit_line(lead)}"
    if settings.address:
        text += f"\n📍 {escape(settings.address)}"
    text += "\n\nЕсли планы изменились, отмените запись кнопкой ниже — мы предложим время другим."
    return text


def lead_card(lead: dict) -> str:
    text = (
        f"<b>Заявка №{lead['id']}</b> · {STATUSES[lead['status']]}\n"
        f"{visit_line(lead)}\n"
        f"Имя: {escape(lead['name'])}\n"
        f"Телефон: {format_phone(lead['phone'])}\n"
        f"Создана: {format_created(lead['created_at'])}"
    )
    if lead["status"] == "canceled" and lead.get("canceled_by") == "client":
        text += "\n<i>Отменил клиент</i>"
    return text


def client_canceled_for_admin(lead: dict) -> str:
    return f"⚠️ Клиент отменил запись — время снова свободно.\n\n{lead_card(lead)}"


def day_schedule(day: date, leads: list[dict]) -> str:
    title = f"<b>Расписание на {format_date_long(day)}</b>"
    if not leads:
        return f"{title}\n\nЗаписей нет."
    rows = []
    for lead in leads:
        mark = "📌" if lead["status"] == "confirmed" else "✅" if lead["status"] == "done" else "🆕"
        rows.append(
            f"{mark} <b>{lead['visit_time']}</b> {escape(lead['service'])} — "
            f"{escape(lead['name'])}, {format_phone(lead['phone'])} (№{lead['id']})"
        )
    return f"{title}\n\n" + "\n".join(rows) + "\n\n🆕 — ждёт подтверждения, 📌 — подтверждена"
