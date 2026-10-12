import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

logger = logging.getLogger(__name__)

LEXICON_COMMANDS_RU: dict[str, str] = {
    "/start": "Главное меню",
}

LEXICON_ADMIN_COMMANDS_RU: dict[str, str] = {
    **LEXICON_COMMANDS_RU,
    "/role": "[1|2] Смена роли: 1 — топ-115, 2 — гость",
    "/user": "[user_id|username] Данные о пользователе",
    "/open_debates": "[1|0] Открыть/закрыть запись на дебаты",
    "/export_debates": "CSV с записями на дебаты",
}


def _commands(lexicon: dict[str, str]) -> list[BotCommand]:
    return [BotCommand(command=command, description=description) for command, description in lexicon.items()]


async def set_main_menu(bot: Bot, admin_ids: list[int]):
    """Всем — только /start, админам — еще и админские команды"""
    await bot.set_my_commands(_commands(LEXICON_COMMANDS_RU), scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(_commands(LEXICON_ADMIN_COMMANDS_RU), scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            # Админ еще не писал боту — чат недоступен
            logger.warning(f"Не удалось установить меню команд для админа {admin_id}: {e}")
