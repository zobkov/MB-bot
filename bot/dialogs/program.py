import logging
from html import escape
from typing import Any

from aiogram import F
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Column, ListGroup, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from bot.dialogs.common import BACK_TEXT
from bot.states import MainParticipantSG
from config.config import Config, ProgramItem
from database.db import Database
from database.models import User
from database.repositories import (
    DebateRepository,
    ParallelRepository,
    ParallelSeats,
    RegisterResult,
    SettingsRepository,
)
from services.users import get_db_user, is_main_role
from utils.logging_config import log_user_action

logger = logging.getLogger(__name__)

CHECK = "✅"
LOCK = "🔒"
PEN = "✍️"


async def program_flags(db: Database) -> tuple[bool, bool]:
    """(программа открыта, запись на параллельные мероприятия открыта)"""
    session = await db.get_session()
    try:
        settings = SettingsRepository(session)
        return (
            await settings.get_bool(SettingsRepository.PROGRAM_OPEN),
            await settings.get_bool(SettingsRepository.PARALLEL_OPEN),
        )
    finally:
        await session.close()


async def _load_parallel(db: Database, user_id: int | None) -> tuple[dict[str, ParallelSeats], dict[str, str]]:
    """Места по мероприятиям {code: seats} и записи пользователя {slot_code: event_code}"""
    session = await db.get_session()
    try:
        repo = ParallelRepository(session)
        seats = {s.code: s for s in await repo.get_seats()}
        mine = await repo.get_user_events(user_id) if user_id else {}
    finally:
        await session.close()
    return seats, mine


def _current_item(manager: DialogManager) -> ProgramItem | None:
    config: Config = manager.middleware_data["config"]
    found = config.conference.program.get_item(manager.dialog_data.get("item_code", ""))
    return found[1] if found else None


def _item_title(config: Config, code: str) -> str:
    found = config.conference.program.get_item(code)
    return found[1].title if found else code


# ============================================================================
# ГЕТТЕРЫ
# ============================================================================

async def get_days_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    return {"days": [{"code": d.code, "title": d.title} for d in config.conference.program.days]}


async def get_day_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    db: Database = dialog_manager.middleware_data["db"]
    day = config.conference.program.get_day(dialog_manager.dialog_data.get("day_code", ""))
    if day is None:
        return {"day_title": "День не найден", "hint": "", "items": []}

    has_slots = any(item.slot for item in day.items)
    _, parallel_open = await program_flags(db)
    seats: dict[str, ParallelSeats] = {}
    mine: dict[str, str] = {}
    if has_slots:
        db_user = await get_db_user(db, dialog_manager.event.from_user.id)
        seats, mine = await _load_parallel(db, db_user.id if db_user else None)
    registered = set(mine.values())

    # Мероприятия подряд с одинаковым временем — параллельные: одна строка кнопок и один блок в расписании
    groups: list[list[ProgramItem]] = []
    for item in day.items:
        if groups and item.time and groups[-1][0].time == item.time:
            groups[-1].append(item)
        else:
            groups.append([item])

    blocks = []
    rows = []
    for pos, group in enumerate(groups):
        lines = [f"<b>{escape(group[0].time)}</b>"] if group[0].time else []
        events = []
        for item in group:
            if item.code in registered:
                mark = f"{CHECK} "
            elif item.slot and parallel_open and item.slot not in mine and item.code in seats and seats[item.code].free > 0:
                # В этом слоте еще ничего не выбрано, а здесь есть места
                mark = f"{PEN} "
            else:
                mark = ""
            place = f" · {escape(item.place)}" if item.place else ""
            lines.append(f"{mark}{escape(item.title)}{place}")
            events.append({"code": item.code, "label": f"{mark}{item.alias}"})
        blocks.append("\n".join(lines))
        rows.append({"id": str(pos), "events": events})

    hint = ""
    if has_slots and parallel_open:
        hint = (
            f"\n\n{PEN} — на мероприятие нужна запись, в одно время можно выбрать только одно.\n"
            f"{CHECK} — ты записан."
        )
    return {
        "day_title": escape(day.title),
        "schedule": "\n\n".join(blocks),
        "hint": hint,
        "rows": rows,
    }


async def get_item_data(dialog_manager: DialogManager, **kwargs):
    config: Config = dialog_manager.middleware_data["config"]
    db: Database = dialog_manager.middleware_data["db"]
    found = config.conference.program.get_item(dialog_manager.dialog_data.get("item_code", ""))
    result = {"card": "Мероприятие не найдено", "can_register": False, "is_full": False, "can_cancel": False}
    if found is None:
        return result
    day, item = found

    when = ", ".join(x for x in (day.date, item.time) if x)
    lines = [f"<b>{escape(item.title)}</b>", f"🗓 {escape(when)}"]
    if item.place:
        lines.append(f"📍 {escape(item.place)}")
    card = "\n".join(lines)
    # description — готовый HTML из program.json, не экранируем
    if item.description:
        card += f"\n\n{item.description}"

    status = []
    if item.slot or item.show_debate_choice:
        db_user = await get_db_user(db, dialog_manager.event.from_user.id)
        user_id = db_user.id if db_user else None

        if item.slot:
            _, parallel_open = await program_flags(db)
            seats, mine = await _load_parallel(db, user_id)
            current = mine.get(item.slot)
            registered = current == item.code
            if registered:
                status.append(f"{CHECK} <b>Ты записан на это мероприятие</b>")
            elif current:
                status.append(f"В это время ты записан на «{escape(_item_title(config, current))}»")

            s = seats.get(item.code)
            if parallel_open and s:
                status.append(f"Свободно мест: {s.free}/{s.capacity}")
                result.update(
                    can_register=not registered and s.free > 0,
                    is_full=not registered and s.free == 0,
                    can_cancel=registered,
                )
            elif not registered:
                status.append(f"{LOCK} Запись на это мероприятие закрыта")

        if item.show_debate_choice and user_id:
            session = await db.get_session()
            try:
                choice = await DebateRepository(session).get_user_choice(user_id)
            finally:
                await session.close()
            if choice:
                titles = {c.code: c.title for c in config.conference.debate_companies}
                status.append(f"{CHECK} Ты записан на дебаты: <b>{escape(titles.get(choice, choice))}</b>")

    if status:
        card += "\n\n" + "\n".join(status)
    result["card"] = card
    return result


async def get_confirm_data(dialog_manager: DialogManager, **kwargs):
    item = _current_item(dialog_manager)
    return {
        "title": escape(item.title) if item else "",
        "current_title": escape(dialog_manager.dialog_data.get("current_title", "")),
    }


# ============================================================================
# ХЕНДЛЕРЫ
# ============================================================================

async def _ensure_program_open(callback: CallbackQuery, manager: DialogManager) -> bool:
    """Программу могли закрыть, пока пользователь сидел в окне"""
    program_open, _ = await program_flags(manager.middleware_data["db"])
    if not program_open:
        await callback.answer("Программа пока закрыта", show_alert=True)
        await manager.switch_to(MainParticipantSG.main)
    return program_open


async def on_day_selected(callback: CallbackQuery, widget: Any, manager: DialogManager, item_id: str):
    if not await _ensure_program_open(callback, manager):
        return
    manager.dialog_data["day_code"] = item_id
    await manager.switch_to(MainParticipantSG.program_day)


async def on_item_selected(callback: CallbackQuery, widget: Any, manager: DialogManager, item_id: str):
    if not await _ensure_program_open(callback, manager):
        return
    manager.dialog_data["item_code"] = item_id
    await manager.switch_to(MainParticipantSG.program_item)


async def _registration_user(callback: CallbackQuery, manager: DialogManager) -> User | None:
    """Пользователь, если запись сейчас возможна; иначе — уведомление и None"""
    db: Database = manager.middleware_data["db"]
    program_open, parallel_open = await program_flags(db)
    if not (program_open and parallel_open):
        await callback.answer("Запись на мероприятия закрыта", show_alert=True)
        return None

    db_user = await get_db_user(db, callback.from_user.id)
    if not is_main_role(db_user):
        await callback.answer("Запись доступна только участникам конференции", show_alert=True)
        return None
    return db_user


async def _register(callback: CallbackQuery, manager: DialogManager, user_id: int, item: ProgramItem) -> None:
    """Записывает пользователя и сообщает результат всплывающим уведомлением"""
    db: Database = manager.middleware_data["db"]
    session = await db.get_session()
    try:
        result = await ParallelRepository(session).register(user_id, item.code)
    finally:
        await session.close()

    log_user_action(callback.from_user.id, callback.from_user.username, "PARALLEL_REGISTER", f"{item.code}: {result.value}")

    if result == RegisterResult.OK:
        await callback.answer(f"{CHECK} Ты записан на «{item.title}»")
    elif result == RegisterResult.FULL:
        await callback.answer(f"Свободных мест на «{item.title}» больше нет 😔", show_alert=True)
    elif result == RegisterResult.SAME:
        await callback.answer(f"Ты уже записан на «{item.title}»")
    else:
        await callback.answer("Такого мероприятия нет", show_alert=True)


async def on_register(callback: CallbackQuery, button: Button, manager: DialogManager):
    item = _current_item(manager)
    if item is None or not item.slot:
        return
    db_user = await _registration_user(callback, manager)
    if db_user is None:
        return

    _, mine = await _load_parallel(manager.middleware_data["db"], db_user.id)
    current = mine.get(item.slot)
    if current is None or current == item.code:
        await _register(callback, manager, db_user.id, item)
        return

    # Смена мероприятия в слоте — сначала предупреждение
    manager.dialog_data["current_title"] = _item_title(manager.middleware_data["config"], current)
    await manager.switch_to(MainParticipantSG.parallel_confirm)


async def on_change_confirmed(callback: CallbackQuery, button: Button, manager: DialogManager):
    item = _current_item(manager)
    if item is None or not item.slot:
        return
    db_user = await _registration_user(callback, manager)
    if db_user is None:
        return
    await _register(callback, manager, db_user.id, item)


async def on_full(callback: CallbackQuery, button: Button, manager: DialogManager):
    await callback.answer("Свободных мест нет 😔")


async def on_cancel_confirmed(callback: CallbackQuery, button: Button, manager: DialogManager):
    item = _current_item(manager)
    if item is None or not item.slot:
        return
    db_user = await _registration_user(callback, manager)
    if db_user is None:
        return

    db: Database = manager.middleware_data["db"]
    session = await db.get_session()
    try:
        deleted = await ParallelRepository(session).cancel(db_user.id, item.code)
    finally:
        await session.close()

    log_user_action(callback.from_user.id, callback.from_user.username, "PARALLEL_CANCEL", f"{item.code}: {deleted}")
    await callback.answer("Запись отменена" if deleted else "Записи на это мероприятие не было")


# ============================================================================
# ОКНА (часть диалога MainParticipantSG)
# ============================================================================

def program_windows() -> list[Window]:
    return [
        Window(
            Const("<b>Программа конференции</b>\n\nВыбери день"),
            Column(
                Select(
                    Format("{item[title]}"),
                    id="program_day",
                    item_id_getter=lambda item: item["code"],
                    items="days",
                    on_click=on_day_selected,
                ),
            ),
            SwitchTo(Const(BACK_TEXT), id="program_back", state=MainParticipantSG.main),
            state=MainParticipantSG.program,
            getter=get_days_data,
        ),
        Window(
            Format(
                "<b>{day_title}</b>\n\n"
                "{schedule}\n\n"
                "Нажми на мероприятие, чтобы узнать подробности.{hint}"
            ),
            # Строка кнопок на каждый блок расписания: параллельные мероприятия — рядом
            ListGroup(
                Select(
                    Format("{item[label]}"),
                    id="program_item",
                    item_id_getter=lambda item: item["code"],
                    items=F["item"]["events"],
                    on_click=on_item_selected,
                ),
                id="day_rows",
                item_id_getter=lambda row: row["id"],
                items="rows",
            ),
            SwitchTo(Const(BACK_TEXT), id="day_back", state=MainParticipantSG.program),
            state=MainParticipantSG.program_day,
            getter=get_day_data,
        ),
        Window(
            Format("{card}"),
            Button(Const("Записаться"), id="parallel_register", on_click=on_register, when="can_register"),
            Button(Const("Мест нет"), id="parallel_full", on_click=on_full, when="is_full"),
            SwitchTo(
                Const("Отменить запись"), id="to_parallel_cancel",
                state=MainParticipantSG.parallel_cancel, when="can_cancel",
            ),
            SwitchTo(Const(BACK_TEXT), id="item_back", state=MainParticipantSG.program_day),
            state=MainParticipantSG.program_item,
            getter=get_item_data,
        ),
        Window(
            Format(
                "<b>Смена записи</b>\n\n"
                "В это время ты записан на <b>{current_title}</b>.\n"
                "Если перейдешь на <b>{title}</b>, твое место на <b>{current_title}</b> "
                "сразу сможет занять кто-то другой, и вернуться может не получиться.\n\n"
                "Сменить запись?"
            ),
            SwitchTo(Const("Да"), id="parallel_change_yes", state=MainParticipantSG.program_item, on_click=on_change_confirmed),
            SwitchTo(Const("Нет"), id="parallel_change_no", state=MainParticipantSG.program_item),
            state=MainParticipantSG.parallel_confirm,
            getter=get_confirm_data,
        ),
        Window(
            Format(
                "<b>Отмена записи</b>\n\n"
                "Отменить запись на <b>{title}</b>?\n"
                "Твое место сразу сможет занять кто-то другой, и вернуться может не получиться."
            ),
            SwitchTo(Const("Да"), id="parallel_cancel_yes", state=MainParticipantSG.program_item, on_click=on_cancel_confirmed),
            SwitchTo(Const("Нет"), id="parallel_cancel_no", state=MainParticipantSG.program_item),
            state=MainParticipantSG.parallel_cancel,
            getter=get_confirm_data,
        ),
    ]
