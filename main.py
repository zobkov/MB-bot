import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram_dialog import setup_dialogs
from redis.asyncio import Redis

from bot.dialogs import dialog_error_handler, guest_dialog, main_participant_dialog
from bot.handlers import router
from bot.keyboards.command_menu import set_main_menu
from bot.middlewares import LoggingMiddleware
from config.config import load_config
from database.db import Database
from database.repositories import DebateRepository
from utils.logging_config import log_error, setup_logging


async def main():
    db = None
    redis_client = None
    bot = None
    logger = setup_logging("INFO")
    try:
        # Загружаем конфигурацию
        config = load_config()

        # Настройка логирования с уровнем из конфигурации
        logger = setup_logging(config.log_level)
        logger.info("🚀 Запуск бота...")
        logger.info(
            f"⚙️ Конфигурация загружена: топ-115 по нику — {len(config.conference.main_usernames)}, "
            f"по user_id — {len(config.conference.main_user_ids)}, админов — {len(config.admin_ids)}"
        )

        # Создаем Redis хранилище для FSM
        if config.redis.password:
            redis_client = Redis.from_url(f"redis://:{config.redis.password}@{config.redis.host}:{config.redis.port}/0")
        else:
            redis_client = Redis.from_url(f"redis://{config.redis.host}:{config.redis.port}/0")

        # Проверка подключения к Redis
        await redis_client.ping()
        logger.info(f"🔗 Подключение к Redis установлено: {config.redis.host}:{config.redis.port}")

        storage = RedisStorage(
            redis=redis_client,
            # Свой префикс — Redis может быть общим с ботом отбора волонтеров
            key_builder=DefaultKeyBuilder(prefix="mbconf", with_bot_id=True, with_destiny=True),
            state_ttl=86400 * 2,
            data_ttl=86400 * 2,
        )

        # Создаем бота и диспетчер
        bot = Bot(
            token=config.tg_bot.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher(storage=storage)

        bot_info = await bot.get_me()
        logger.info(f"🤖 Бот подключен: @{bot_info.username} ({bot_info.first_name})")

        # Создаем подключение к базе данных
        db = Database(config)
        logger.info(f"🔗 Подключение к Postgres: {config.db.host}")

        await db.create_tables()
        session = await db.get_session()
        try:
            await DebateRepository(session).sync_companies(config.conference.debate_companies)
        finally:
            await session.close()
        logger.info("🗄️ База данных инициализирована")

        # Middleware для передачи конфигурации и БД
        async def config_middleware(handler, event, data):
            data["config"] = config
            data["db"] = db
            data["bot"] = bot
            return await handler(event, data)

        dp.message.middleware(LoggingMiddleware())
        dp.callback_query.middleware(LoggingMiddleware())
        dp.message.middleware(config_middleware)
        dp.callback_query.middleware(config_middleware)

        # Регистрируем роутеры и диалоги
        dp.include_router(router)
        dp.include_router(main_participant_dialog)
        dp.include_router(guest_dialog)

        setup_dialogs(dp)
        dp.errors.register(dialog_error_handler)
        logger.info("🔧 Роутеры и диалоги настроены")

        logger.info("✅ Бот готов к работе")
        await dp.start_polling(bot)

    except Exception as e:
        log_error(e, "Критическая ошибка при запуске бота")
        raise
    finally:
        try:
            if db:
                await db.close()
            if redis_client:
                await redis_client.aclose()
            if bot:
                await bot.session.close()
            logger.info("🛑 Бот остановлен")
        except Exception as e:
            log_error(e, "Ошибка при остановке бота")


if __name__ == "__main__":
    asyncio.run(main())
