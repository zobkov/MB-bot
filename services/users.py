from aiogram.types import User as TgUser

from config.config import Config, normalize_username
from database.db import Database
from database.models import ROLE_MAIN, User
from database.repositories import UserRepository


def is_main_participant(config: Config, tg_user: TgUser) -> bool:
    """Есть ли пользователь в списке топ-115 (по username из 115users.csv или по user_id из конфига)"""
    if tg_user.id in config.conference.main_user_ids:
        return True
    username = normalize_username(tg_user.username)
    return bool(username and username in config.conference.main_usernames)


def check_is_admin(user_id: int, config: Config | None) -> bool:
    if not config or not config.admin_ids:
        return False
    return user_id in config.admin_ids


async def sync_user(db: Database, config: Config, tg_user: TgUser) -> User:
    """Создает/обновляет пользователя в БД и назначает роль топ-115 по списку"""
    session = await db.get_session()
    try:
        return await UserRepository(session).upsert_user(
            telegram_id=tg_user.id,
            telegram_username=tg_user.username,
            is_main_participant=is_main_participant(config, tg_user),
        )
    finally:
        await session.close()


async def get_db_user(db: Database, telegram_id: int) -> User | None:
    session = await db.get_session()
    try:
        return await UserRepository(session).get_user_by_telegram_id(telegram_id)
    finally:
        await session.close()


def is_main_role(user: User | None) -> bool:
    return bool(user and user.role == ROLE_MAIN)
