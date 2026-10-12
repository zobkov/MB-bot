from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# добавляем корневую директорию в путь
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from database.models import Base
from config.config import load_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# БД может быть общей с ботом отбора волонтеров: у него своя таблица alembic_version,
# поэтому версии этого бота храним отдельно и мигрируем только таблицы conf_*
VERSION_TABLE = "conf_alembic_version"


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and reflected and compare_to is None:
        return name.startswith("conf_")
    return True


def get_url():
    """Получение URL базы данных из конфигурации"""
    app_config = load_config()
    return f"postgresql+psycopg2://{app_config.db.user}:{app_config.db.password}@{app_config.db.host}:{app_config.db.port}/{app_config.db.database}"


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
