import logging
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Column, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from bot.dialogs.common import BACK_TEXT, support_window
from bot.dialogs.program import program_flags, program_windows
from bot.states import MainParticipantSG
from database.db import Database
from database.repositories import DebateRepository, RegisterResult, SettingsRepository
from services.users import get_db_user, is_main_role
from utils.logging_config import log_user_action

logger = logging.getLogger(__name__)

CHECK = "✅"
LOCK = "🔒"


async def _debates_open(db: Database) -> bool:
    session = await db.get_session()
    try:
        return await SettingsRepository(session).get_bool(SettingsRepository.DEBATES_OPEN)
    finally:
        await session.close()


# ============================================================================
# ГЕТТЕРЫ
# ============================================================================

async def get_main_data(dialog_manager: DialogManager, **kwargs):
    db: Database = dialog_manager.middleware_data["db"]
    is_open = await _debates_open(db)
    program_open, parallel_open = await program_flags(db)
    return {
        "debates_open": is_open,
        "debates_closed": not is_open,
        "program_open": program_open,
        "program_closed": not program_open,
        "parallel_open": program_open and parallel_open,
    }


async def get_debates_data(dialog_manager: DialogManager, **kwargs):
    db: Database = dialog_manager.middleware_data["db"]
    tg_user = dialog_manager.event.from_user

    db_user = await get_db_user(db, tg_user.id)
    session = await db.get_session()
    try:
        repo = DebateRepository(session)
        seats = await repo.get_seats()
        choice = await repo.get_user_choice(db_user.id) if db_user else None
    finally:
        await session.close()

    lines = []
    companies = []
    for s in seats:
        mark = f"{CHECK} " if s.code == choice else ""
        lines.append(f"{mark}<b>{s.title}</b> – {s.free}/{s.capacity}")
        companies.append({"code": s.code, "label": f"{mark}{s.title}"})

    return {"seats_text": "\n".join(lines), "companies": companies}


async def get_confirm_data(dialog_manager: DialogManager, **kwargs):
    return {
        "current_title": dialog_manager.dialog_data.get("current_title", ""),
        "pending_title": dialog_manager.dialog_data.get("pending_title", ""),
    }


# ============================================================================
# ХЕНДЛЕРЫ
# ============================================================================

async def _titles(db: Database) -> dict[str, str]:
    session = await db.get_session()
    try:
        return {s.code: s.title for s in await DebateRepository(session).get_seats()}
    finally:
        await session.close()


async def _register(callback: CallbackQuery, manager: DialogManager, user_id: int, code: str) -> None:
    """Записывает пользователя и сообщает результат всплывающим уведомлением"""
    db: Database = manager.middleware_data["db"]
    session = await db.get_session()
    try:
        result = await DebateRepository(session).register(user_id, code)
    finally:
        await session.close()

    title = (await _titles(db)).get(code, code)
    log_user_action(callback.from_user.id, callback.from_user.username, "DEBATES_REGISTER", f"{code}: {result.value}")

    if result == RegisterResult.OK:
        await callback.answer(f"{CHECK} Ты записан на дебаты: {title}")
    elif result == RegisterResult.FULL:
        await callback.answer(f"Свободных мест на «{title}» больше нет 😔", show_alert=True)
    elif result == RegisterResult.SAME:
        await callback.answer(f"Ты уже записан на «{title}»")
    else:
        await callback.answer("Такой компании нет", show_alert=True)


async def on_company_selected(callback: CallbackQuery, widget: Any, manager: DialogManager, item_id: str):
    db: Database = manager.middleware_data["db"]

    # Запись могли закрыть, пока пользователь сидел в окне
    if not await _debates_open(db):
        await callback.answer("Запись на дебаты закрыта", show_alert=True)
        await manager.switch_to(MainParticipantSG.main)
        return

    db_user = await get_db_user(db, callback.from_user.id)
    if not is_main_role(db_user):
        await callback.answer("Запись на дебаты доступна только участникам конференции", show_alert=True)
        return

    session = await db.get_session()
    try:
        current = await DebateRepository(session).get_user_choice(db_user.id)
    finally:
        await session.close()

    if current is None or current == item_id:
        await _register(callback, manager, db_user.id, item_id)
        return

    # Смена компании — сначала предупреждение
    titles = await _titles(db)
    manager.dialog_data.update(
        pending_code=item_id,
        current_title=titles.get(current, current),
        pending_title=titles.get(item_id, item_id),
    )
    await manager.switch_to(MainParticipantSG.debates_confirm)


async def on_change_confirmed(callback: CallbackQuery, button: Button, manager: DialogManager):
    db: Database = manager.middleware_data["db"]
    code = manager.dialog_data.pop("pending_code", None)
    if not code:
        return

    if not await _debates_open(db):
        await callback.answer("Запись на дебаты закрыта", show_alert=True)
        return

    db_user = await get_db_user(db, callback.from_user.id)
    if not is_main_role(db_user):
        return
    await _register(callback, manager, db_user.id, code)


# ============================================================================
# ДИАЛОГ
# ============================================================================

main_participant_dialog = Dialog(
    Window(
        Const(
            "<b>Главное меню</b>\n\n"
            "Запись на дебаты закрыта. Скоро тут появятся новые функции",
            when="program_closed",
        ),
        Const(
            "<b>Главное меню</b>\n\n"
            "В разделе «Программа» — расписание всех трех дней конференции",
            when="program_open",
        ),
        Const(
            "\nОткрыта запись на параллельные мероприятия 23 октября — выбирай их в программе второго дня",
            when="parallel_open",
        ),
        SwitchTo(Const("Программа"), id="to_program", state=MainParticipantSG.program, when="program_open"),
        # Пока программа закрыта, кнопка ничего не делает
        Button(Const(f"{LOCK} Программа"), id="program_locked", when="program_closed"),
        SwitchTo(Const("Поддержка"), id="to_support", state=MainParticipantSG.support),
        state=MainParticipantSG.main,
        getter=get_main_data,
    ),
    support_window(MainParticipantSG.support, MainParticipantSG.main),
    *program_windows(),
    Window(
        Format(
            "<b>Запись на дебаты</b>\n\n"
            "Свободные места:\n"
            "{seats_text}\n\n"
            "Для записи нажми на кнопку снизу.\n"
            "<i>Для смены записи нажми на другую кнопку, но при смене компаний кто-то другой сможет занять твое место.</i>"
        ),
        Column(
            Select(
                Format("{item[label]}"),
                id="debate_company",
                item_id_getter=lambda item: item["code"],
                items="companies",
                on_click=on_company_selected,
            ),
        ),
        SwitchTo(Const(BACK_TEXT), id="debates_back", state=MainParticipantSG.main),
        state=MainParticipantSG.debates,
        getter=get_debates_data,
    ),
    Window(
        Format(
            "<b>Смена записи на дебаты</b>\n\n"
            "Сейчас ты записан на <b>{current_title}</b>.\n"
            "Если перейдешь на <b>{pending_title}</b>, твое место на <b>{current_title}</b> "
            "сразу сможет занять кто-то другой, и вернуться может не получиться.\n\n"
            "Сменить запись?"
        ),
        SwitchTo(Const("Да"), id="change_yes", state=MainParticipantSG.debates, on_click=on_change_confirmed),
        SwitchTo(Const("Нет"), id="change_no", state=MainParticipantSG.debates),
        state=MainParticipantSG.debates_confirm,
        getter=get_confirm_data,
    ),
)
