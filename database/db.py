from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.config import Config
from database.models import Base
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, config: Config):
        self.config = config
        db_url = f"postgresql+asyncpg://{config.db.user}:{config.db.password}@{config.db.host}:{config.db.port}/{config.db.database}"
        
        self.engine = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def create_tables(self):
        """Создание таблиц"""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise

    async def get_session(self) -> AsyncSession:
        """Получение сессии базы данных"""
        return self.session_factory()

    async def close(self):
        """Закрытие соединения с базой данных"""
        await self.engine.dispose()
