import csv
import io
from datetime import datetime
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from aiogram_dialog import DialogManager, StartMode

from bot.states import GuestSG, MainParticipantSG
from config.config import Config, normalize_username
from database.db import Database
from database.models import ROLE_GUEST, ROLE_MAIN, User
from database.repositories import DebateRepository, SettingsRepository, UserRepository
from services.users import check_is_admin, is_main_role, sync_user
from utils.logging_config import log_user_action

router = Router()

ACCESS_DENIED = "⛔️ <b>Доступ запрещен.</b> У вас нет прав администратора."
ROLE_TITLES = {ROLE_MAIN: "участник топ-115", ROLE_GUEST: "гость"}


async def open_menu_for_role(dialog_manager: DialogManager, user: User) -> None:
    """Каждая роль — отдельный диалог. Выбор диалога только здесь, по роли из БД."""
    state = MainParticipantSG.main if is_main_role(user) else GuestSG.main
    await dialog_manager.start(state, mode=StartMode.RESET_STACK)


@router.message(Command("start"))
async def cmd_start(message: Message, dialog_manager: DialogManager, db: Database, config: Config):
    user = await sync_user(db, config, message.from_user)
    log_user_action(message.from_user.id, message.from_user.username, "START", f"role={user.role}")
    await open_menu_for_role(dialog_manager, user)


# ============================================================================
# АДМИНИСТРАТИВНЫЕ КОМАНДЫ (проверка прав)
# ============================================================================

@router.message(Command("role"))
async def cmd_role(message: Message, command: CommandObject, dialog_manager: DialogManager, db: Database, config: Config):
    """/role [1|2] — смена своей роли: 1 — топ-115, 2 — гость"""
    if not check_is_admin(message.from_user.id, config):
        await message.answer(ACCESS_DENIED)
        return

    arg = (command.args or "").strip()
    roles = {"1": ROLE_MAIN, "2": ROLE_GUEST}
    if arg not in roles:
        await message.answer("Использование: <code>/role 1</code> — топ-115, <code>/role 2</code> — гость")
        return

    await sync_user(db, config, message.from_user)
    session = await db.get_session()
    try:
        user = await UserRepository(session).set_role(message.from_user.id, roles[arg])
    finally:
        await session.close()

    log_user_action(message.from_user.id, message.from_user.username, "ADMIN_ROLE", roles[arg])
    await message.answer(f"Роль изменена: <b>{ROLE_TITLES[user.role]}</b>")
    await open_menu_for_role(dialog_manager, user)


async def _find_user(user_repo: UserRepository, arg: str) -> User | None:
    """Поиск по user_id или username (с @ или без)"""
    if arg.isdigit():
        return await user_repo.get_user_by_telegram_id(int(arg))
    return await user_repo.get_user_by_username(normalize_username(arg) or "")


@router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject, db: Database, config: Config):
    """/user [user_id|username] — данные о пользователе из БД"""
    if not check_is_admin(message.from_user.id, config):
        await message.answer(ACCESS_DENIED)
        return

    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Использование: <code>/user 123456789</code> или <code>/user @username</code>")
        return

    session = await db.get_session()
    try:
        user = await _find_user(UserRepository(session), arg)
        if user is None:
            await message.answer(f"Пользователь <code>{escape(arg)}</code> не найден в БД")
            return

        debate_repo = DebateRepository(session)
        choice = await debate_repo.get_user_choice(user.id)
        titles = {s.code: s.title for s in await debate_repo.get_seats()}
    finally:
        await session.close()

    username = normalize_username(user.telegram_username)
    in_list = user.telegram_id in config.conference.main_user_ids or (
        username is not None and username in config.conference.main_usernames
    )
    debates = f"{titles.get(choice, choice)} ({choice})" if choice else "нет записи"

    await message.answer(
        "<b>Пользователь</b>\n\n"
        f"user_id: <code>{user.telegram_id}</code>\n"
        f"username: {'@' + escape(user.telegram_username) if user.telegram_username else '—'}\n"
        f"Роль: <b>{ROLE_TITLES.get(user.role, user.role)}</b>"
        f"{' (выставлена вручную)' if user.role_overridden else ''}\n"
        f"В списке топ-115: {'да' if in_list else 'нет'}\n"
        f"Админ: {'да' if check_is_admin(user.telegram_id, config) else 'нет'}\n"
        f"Дебаты: {escape(debates)}\n"
        f"Первый вход: {user.created_at:%d.%m.%Y %H:%M}"
    )


@router.message(Command("cancel_debates"))
async def cmd_cancel_debates(message: Message, command: CommandObject, db: Database, config: Config):
    """/cancel_debates [user_id|username] — удалить запись на дебаты (без аргумента — свою)"""
    if not check_is_admin(message.from_user.id, config):
        await message.answer(ACCESS_DENIED)
        return

    arg = (command.args or "").strip() or str(message.from_user.id)

    session = await db.get_session()
    try:
        user = await _find_user(UserRepository(session), arg)
        if user is None:
            await message.answer(f"Пользователь <code>{escape(arg)}</code> не найден в БД")
            return

        debate_repo = DebateRepository(session)
        code = await debate_repo.cancel(user.id)
        seats = {s.code: s for s in await debate_repo.get_seats()}
    finally:
        await session.close()

    who = f"@{escape(user.telegram_username)}" if user.telegram_username else f"<code>{user.telegram_id}</code>"
    if code is None:
        await message.answer(f"У {who} нет записи на дебаты")
        return

    log_user_action(message.from_user.id, message.from_user.username, "ADMIN_CANCEL_DEBATES", f"{user.telegram_id}: {code}")
    s = seats.get(code)
    await message.answer(
        f"Запись {who} на <b>{escape(s.title if s else code)}</b> удалена"
        + (f"\nСвободно: {s.free}/{s.capacity}" if s else "")
    )


@router.message(Command("open_debates"))
async def cmd_open_debates(message: Message, command: CommandObject, db: Database, config: Config):
    """/open_debates [1|0] — открыть/закрыть запись на дебаты"""
    if not check_is_admin(message.from_user.id, config):
        await message.answer(ACCESS_DENIED)
        return

    arg = (command.args or "").strip()
    session = await db.get_session()
    try:
        settings = SettingsRepository(session)
        if arg not in ("0", "1"):
            is_open = await settings.get_bool(SettingsRepository.DEBATES_OPEN)
            await message.answer(
                f"Запись на дебаты сейчас <b>{'открыта' if is_open else 'закрыта'}</b>.\n\n"
                "Использование: <code>/open_debates 1</code> — открыть, <code>/open_debates 0</code> — закрыть"
            )
            return
        await settings.set_bool(SettingsRepository.DEBATES_OPEN, arg == "1")
    finally:
        await session.close()

    log_user_action(message.from_user.id, message.from_user.username, "ADMIN_OPEN_DEBATES", arg)
    await message.answer(f"Запись на дебаты <b>{'открыта' if arg == '1' else 'закрыта'}</b>")


@router.message(Command("export_debates"))
async def cmd_export_debates(message: Message, db: Database, config: Config):
    """/export_debates — CSV с записями на дебаты"""
    if not check_is_admin(message.from_user.id, config):
        await message.answer(ACCESS_DENIED)
        return

    session = await db.get_session()
    try:
        debate_repo = DebateRepository(session)
        rows = await debate_repo.export_rows()
        seats = await debate_repo.get_seats()
    finally:
        await session.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "username", "debate_choice"])
    for telegram_id, username, code in rows:
        writer.writerow([telegram_id, username or "", code])

    filename = f"debates_{datetime.now():%Y%m%d_%H%M}.csv"
    summary = "\n".join(f"{s.title}: {s.taken}/{s.capacity}" for s in seats)
    log_user_action(message.from_user.id, message.from_user.username, "ADMIN_EXPORT_DEBATES", f"{len(rows)} rows")
    await message.answer_document(
        BufferedInputFile(buffer.getvalue().encode("utf-8"), filename=filename),
        caption=f"Записей: {len(rows)}\n{summary}",
    )
