# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Telegram-бот Конференции «Менеджмент Будущего» (МБ) 2026 — основной интерфейс конференции для трех групп:

- **Участники топ-115** (`role = "main"`) — программа, запись на параллельные мероприятия и на управленческие дебаты.
- **Гости** (`role = "guest"`, роль по умолчанию) — запись на открытые мероприятия, информация, связь с оргами.
- **Админы** (оргкомитет) — не отдельная роль, а флаг по `ADMIN_IDS` в `.env`; переключаются между ролями командой `/role 1|2` для отладки.

**Текущий этап:** реализована только регистрация участников топ-115 на дебаты. Программа — заглушка (кнопка с замком, без действия). Функционал гостей — только главное меню и поддержка.

Архитектура и стек напрямую заимствованы из бота отбора волонтеров МБ (https://github.com/zobkov/MB_bots-vol_selection) — при сомнениях смотри, как сделано там, и делай так же.

Все на русском: тексты для пользователей, логи, комментарии в коде.

## Commands

```bash
poetry install --no-root             # зависимости
poetry run alembic upgrade head      # миграции
poetry run python main.py            # запуск бота (long polling)
./start.sh                           # .env check + poetry install + alembic upgrade + запуск
poetry run alembic revision --autogenerate -m "description"   # новая миграция
poetry run alembic check             # модели и схема БД совпадают?
```

Тестов и линтера нет.

## Shared infrastructure — важно

Postgres и Redis из `.env` **общие с ботом отбора волонтеров** (в той же БД лежат его таблицы `users`, `applications`, `stage2_applications`). Поэтому:

- Все таблицы этого бота — с префиксом `conf_` (`conf_users`, `conf_debate_companies`, `conf_debate_registrations`, `conf_settings`). Никогда не создавать/менять таблицы без префикса.
- Alembic хранит версии в `conf_alembic_version` и через `include_object` в `alembic/env.py` видит только таблицы `conf_*` — autogenerate не должен предлагать удалить чужие таблицы. Проверяй сгенерированные миграции глазами.
- Ключи FSM в Redis идут с префиксом `mbconf` (`DefaultKeyBuilder` в `main.py`).
- Не писать тестовые данные в эту БД без явного разрешения.

## Architecture

**Entry point** `main.py`: `load_config()` → Redis (`RedisStorage`) → `Bot`/`Dispatcher` → `Database` + `create_tables()` + синхронизация компаний дебатов из конфига → `config_middleware` (кладет `config`, `db`, `bot` в data каждого хендлера) + `LoggingMiddleware` → роутер команд + диалоги → `setup_dialogs(dp)` → `dialog_error_handler` → меню команд → polling.

**Config** (`config/config.py`) — один dataclass `Config` из двух источников: `.env` (секреты и подключения: `BOT_TOKEN`, `DB_*`, `REDIS_*`, `ADMIN_IDS`, `ADMIN_NOTIFICATION`, `LOG_LEVEL`) и `config/conference_config.json` (несекретное: контакты, компании дебатов с вместимостью, путь к CSV топ-115, `extra_user_ids` для участников без username). Вместимость компаний меняется в JSON и применяется при перезапуске.

**Роли и маршрутизация.** Список топ-115 — `115users.csv` (колонка `username`, с `@`) + `extra_user_ids` из конфига. `services/users.py::sync_user` вызывается в `/start`: upsert пользователя в `conf_users`, и если ник/ID в списке — роль повышается до `main`. Автоматического понижения нет; `/role` ставит `role_overridden = true`, после чего автоназначение роль не трогает. Сравнение ников — через `normalize_username` (без `@`, lower-case).

**Диалоги** (`bot/dialogs/`) — по одному `Dialog` на роль, не ветвление внутри одного диалога: `main_participant.py` (`MainParticipantSG`), `guest.py` (`GuestSG`). Какой диалог открыть, решает только `/start` (`bot/handlers.py::open_menu_for_role`) по роли из БД. Общие окна (поддержка) — фабрики в `common.py`. Новая роль = новый `StatesGroup` в `bot/states/__init__.py` + новый модуль диалога + ветка в `open_menu_for_role` + `include_router` в `main.py`.

**Навигация в меню — только `SwitchTo`** (виджет или `manager.switch_to` в хендлере, когда переход условный). Не использовать `Start`/`Next`/`Back`/`Cancel` для перемещения по меню. Закрытые разделы — `Button` без `on_click` с 🔒 в тексте (кнопка «не отвечает»), открытые — `SwitchTo`; переключение через `when=` и флаг из геттера.

**Запись на дебаты.** Флаг открытия — `conf_settings.debates_open` (`/open_debates 1|0`), читается в геттере на каждый показ, поэтому после `/start` замок пропадает без перезапуска. Хендлер выбора повторно проверяет флаг и роль. Первая запись — сразу; смена компании — через окно подтверждения `debates_confirm` (код выбранной компании в `dialog_data`).

**Race conditions** (`database/repositories.py::DebateRepository.register`): одна транзакция — `SELECT ... FOR UPDATE` строки компании (сериализует всех, кто пишется в эту компанию) → `FOR UPDATE` записи пользователя → подсчет занятых мест → `INSERT ... ON CONFLICT (user_id) DO UPDATE`. Уникальность `user_id` в `conf_debate_registrations` гарантирует одну запись на человека. Порядок блокировок всегда «компания → пользователь». Любая новая логика с ограниченными местами (параллельные мероприятия) должна следовать той же схеме, а не «проверить в геттере, потом вставить».

**Database** (`database/`): `models.py` — модели, `db.py` — async engine/sessionmaker, `repositories.py` — весь доступ к БД (`UserRepository`, `SettingsRepository`, `DebateRepository`); никаких запросов напрямую из диалогов/хендлеров. Паттерн сессии: `session = await db.get_session()` / `try` / `finally: await session.close()`. `create_tables()` на старте + миграции в `alembic/versions/` — держать в синхроне (`alembic check`). Alembic работает через `psycopg2` (sync), бот — через `asyncpg`.

**Admin commands** (`bot/handlers.py`, проверка `check_is_admin` по `config.admin_ids`): `/role 1|2`, `/user <user_id|username>`, `/open_debates [1|0]` (без аргумента — показать статус), `/cancel_debates [user_id|username]` (удалить запись; без аргумента — свою), `/export_debates` (CSV `user_id,username,debate_choice` с алиасами `VTB`, `AlfaNSeverstal`, `B1` = `code` компании). Не-админам в меню команд показывается только `/start` (`bot/keyboards/command_menu.py`, админам — через `BotCommandScopeChat`).

**Logging** (`utils/logging_config.py`, скопирован из бота волонтеров): файлы в `logs/` (`bot.log`, `database.log`, `errors.log`, `user_actions.log`). Использовать хелперы `log_user_action`, `log_db_operation`, `log_error` вместо прямого `logging`.

**Тексты.** Тексты окон взяты из ТЗ (`prompt.md`) дословно, включая опечатки — не «исправлять» без запроса. HTML parse mode по умолчанию. Кастомные premium-эмодзи (`utils/emojis.py` в боте волонтеров) здесь пока не используются.
