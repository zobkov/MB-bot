import logging
from html import escape
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Column, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from bot.dialogs.common import BACK_TEXT, support_window
from bot.states import GuestSG
from config.config import Config
from database.db import Database
from database.repositories import EventRepository, EventSeats, RegisterResult, SettingsRepository
from services.users import get_db_user
from utils.logging_config import log_user_action

logger = logging.getLogger(__name__)

CHECK = "✅"
LOCK = "🔒"


async def _events_open(db: Database) -> bool:
    session = await db.get_session()
    try:
        return await SettingsRepository(session).get_bool(SettingsRepository.EVENTS_OPEN)
    finally:
        await session.close()


async def _load_events(db: Database, telegram_id: int) -> tuple[list[EventSeats], set[str]]:
    """Все мероприятия с местами и коды мероприятий, на которые записан пользователь"""
    db_user = await get_db_user(db, telegram_id)
    session = await db.get_session()
    try:
        repo = EventRepository(session)
        seats = await repo.get_seats()
        mine = await repo.get_user_events(db_user.id) if db_user else set()
    finally:
        await session.close()
    return seats, mine


# ============================================================================
# ГЕТТЕРЫ
# ============================================================================

async def get_guest_main_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    db: Database = dialog_manager.middleware_data["db"]
    is_open = await _events_open(db)
    return {
        "tech_contact": config.conference.tech_contact,
        "events_open": is_open,
        "events_closed": not is_open,
    }


async def get_events_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    db: Database = dialog_manager.middleware_data["db"]
    seats, mine = await _load_events(db, dialog_manager.event.from_user.id)
    aliases = {e.code: e.alias for e in config.conference.open_events if e.alias}

    lines = []
    events = []
    for s in seats:
        mark = f"{CHECK} " if s.code in mine else ""
        lines.append(f"{mark}<b>{escape(s.title)}</b>\n{escape(s.schedule)} · свободно {s.free}/{s.capacity}")
        events.append({"code": s.code, "label": f"{mark}{aliases.get(s.code, s.title)}"})

    return {"events_text": "\n\n".join(lines), "events": events}


async def get_event_data(dialog_manager: DialogManager, **kwargs):
    db: Database = dialog_manager.middleware_data["db"]
    code = dialog_manager.dialog_data.get("event_code")
    seats, mine = await _load_events(db, dialog_manager.event.from_user.id)
    event = next((s for s in seats if s.code == code), None)

    if event is None:
        return {
            "title": "Мероприятие не найдено", "schedule": "", "description": "", "free": 0, "capacity": 0,
            "status": "", "can_register": False, "is_full": False, "registered": False,
        }

    registered = code in mine
    return {
        "title": escape(event.title),
        "schedule": escape(event.schedule),
        # description — готовый HTML карточки из конфига, не экранируем
        "description": event.description,
        "free": event.free,
        "capacity": event.capacity,
        "status": f"\n\n{CHECK} <b>Ты записан на это мероприятие</b>" if registered else "",
        "registered": registered,
        "can_register": not registered and event.free > 0,
        "is_full": not registered and event.free == 0,
    }


# ============================================================================
# ХЕНДЛЕРЫ
# ============================================================================

async def on_event_selected(callback: CallbackQuery, widget: Any, manager: DialogManager, item_id: str):
    manager.dialog_data["event_code"] = item_id
    await manager.switch_to(GuestSG.event)


async def on_register(callback: CallbackQuery, button: Button, manager: DialogManager):
    db: Database = manager.middleware_data["db"]
    code = manager.dialog_data.get("event_code")
    if not code:
        return

    # Запись могли закрыть, пока пользователь сидел в окне
    if not await _events_open(db):
        await callback.answer("Запись на мероприятия закрыта", show_alert=True)
        await manager.switch_to(GuestSG.main)
        return

    db_user = await get_db_user(db, callback.from_user.id)
    if db_user is None:
        await callback.answer("Нажми /start и попробуй еще раз", show_alert=True)
        return

    session = await db.get_session()
    try:
        result = await EventRepository(session).register(db_user.id, code)
    finally:
        await session.close()

    log_user_action(callback.from_user.id, callback.from_user.username, "EVENT_REGISTER", f"{code}: {result.value}")

    if result == RegisterResult.OK:
        await callback.answer(f"{CHECK} Ты записан на мероприятие")
    elif result == RegisterResult.FULL:
        await callback.answer("Свободных мест больше нет 😔", show_alert=True)
    elif result == RegisterResult.SAME:
        await callback.answer("Ты уже записан на это мероприятие")
    else:
        await callback.answer("Такого мероприятия нет", show_alert=True)


async def on_full(callback: CallbackQuery, button: Button, manager: DialogManager):
    await callback.answer("Свободных мест нет 😔")


async def on_cancel_confirmed(callback: CallbackQuery, button: Button, manager: DialogManager):
    db: Database = manager.middleware_data["db"]
    code = manager.dialog_data.get("event_code")
    if not code:
        return

    db_user = await get_db_user(db, callback.from_user.id)
    if db_user is None:
        return

    session = await db.get_session()
    try:
        deleted = await EventRepository(session).cancel(db_user.id, code)
    finally:
        await session.close()

    log_user_action(callback.from_user.id, callback.from_user.username, "EVENT_CANCEL", f"{code}: {deleted}")
    await callback.answer("Запись отменена" if deleted else "Записи на это мероприятие не было")


# ============================================================================
# ДИАЛОГ
# ============================================================================

guest_dialog = Dialog(
    Window(
        Format(
            "<b>Главное меню</b>\n\n"
            "Скоро здесь появится информация об открытых мероприятия МБ'26",
            when="events_closed",
        ),
        Format(
            "<b>Главное меню</b>\n\n"
            "Открыта запись на открытые мероприятия МБ'26 – выбирай, куда хочешь прийти",
            when="events_open",
        ),
        SwitchTo(Const("Открытые мероприятия"), id="to_events", state=GuestSG.events, when="events_open"),
        # Пока запись закрыта, кнопка ничего не делает
        Button(Const(f"{LOCK} Открытые мероприятия"), id="events_locked", when="events_closed"),
        SwitchTo(Const("Поддержка"), id="to_support", state=GuestSG.support),
        state=GuestSG.main,
        getter=get_guest_main_data,
    ),
    support_window(GuestSG.support, GuestSG.main),
    Window(
        Format(
            "<b>Открытые мероприятия</b>\n\n"
            "{events_text}\n\n"
            "Нажми на мероприятие, чтобы узнать подробности и записаться."
        ),
        Column(
            Select(
                Format("{item[label]}"),
                id="open_event",
                item_id_getter=lambda item: item["code"],
                items="events",
                on_click=on_event_selected,
            ),
        ),
        SwitchTo(Const(BACK_TEXT), id="events_back", state=GuestSG.main),
        state=GuestSG.events,
        getter=get_events_data,
    ),
    Window(
        Format(
            "{description}\n\n"
            "🗓 {schedule}\n"
            "Свободно мест: {free}/{capacity}"
            "{status}"
        ),
        Button(Const("Записаться"), id="event_register", on_click=on_register, when="can_register"),
        Button(Const("Мест нет"), id="event_full", on_click=on_full, when="is_full"),
        SwitchTo(Const("Отменить запись"), id="to_event_cancel", state=GuestSG.event_cancel, when="registered"),
        SwitchTo(Const(BACK_TEXT), id="event_back", state=GuestSG.events),
        state=GuestSG.event,
        getter=get_event_data,
    ),
    Window(
        Format(
            "<b>Отмена записи</b>\n\n"
            "Отменить запись на <b>{title}</b>?\n"
            "Твое место сразу сможет занять кто-то другой, и вернуться может не получиться."
        ),
        SwitchTo(Const("Да"), id="cancel_yes", state=GuestSG.event, on_click=on_cancel_confirmed),
        SwitchTo(Const("Нет"), id="cancel_no", state=GuestSG.event),
        state=GuestSG.event_cancel,
        getter=get_event_data,
    ),
)
