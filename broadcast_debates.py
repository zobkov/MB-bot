#!/usr/bin/env python3
"""
Разовая рассылка всем, кто записан на дебаты: текст зависит от выбранной компании
и содержит ссылку на чат этой компании для распределения по командам.

Использование:
    poetry run python broadcast_debates.py --dry-run          # показать получателей и тексты, ничего не отправлять
    poetry run python broadcast_debates.py --test 257026813   # отправить все варианты текста одному человеку
    poetry run python broadcast_debates.py                    # разослать (с подтверждением)
    poetry run python broadcast_debates.py --only VTB --yes   # только одной компании, без подтверждения

Получатели — conf_debate_registrations (как в /export_debates). Ссылки на чаты — CHAT_LINKS ниже.
"""

import argparse
import asyncio
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from config.config import load_config
from database.db import Database
from database.repositories import DebateRepository

# ============================================================================
# РЕДАКТИРУЕМЫЕ ПАРАМЕТРЫ РАССЫЛКИ
# ============================================================================

# Ссылки на чаты по коду компании (коды — из config/conference_config.json)
CHAT_LINKS: dict[str, str] = {
    "VTB": "https://t.me/+uZrKhGvdqgk1M2Ni",
    "AlfaNSeverstal": "https://t.me/+fSEe5955CnIzMTYy",
    "B1": "https://t.me/+fzI0GnWWUVkzYTUy",
}

# {company} — название компании, {link} — ссылка из CHAT_LINKS
MESSAGE_TEMPLATE = (
    "Привет! Спасибо за регистрацию на дебаты {company}\n\n"
    "Заходи в чат по ссылке для распределения по командам:\n"
    "{link}"
)

# Telegram Bot API: не более ~30 сообщений/сек в разные чаты
DEFAULT_RATE_PER_SEC = 20
MAX_RATE_PER_SEC = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("broadcast_debates")


def render(company_title: str, code: str) -> str:
    return MESSAGE_TEMPLATE.format(company=company_title, link=CHAT_LINKS[code])


async def load_recipients(only: str | None) -> tuple[list[tuple[int, str | None, str]], dict[str, str]]:
    """Возвращает [(telegram_id, username, company_code)] и {code: title}"""
    config = load_config()
    db = Database(config)
    session = await db.get_session()
    try:
        repo = DebateRepository(session)
        rows = await repo.export_rows()
        titles = {s.code: s.title for s in await repo.get_seats()}
    finally:
        await session.close()
        await db.close()

    if only:
        rows = [r for r in rows if r[2] == only]
    return rows, titles


async def call_with_retry(chat_id: int, send, max_retries: int = 3) -> tuple[bool, str]:
    """Вызывает send(), выжидая при flood-control (429). Возвращает (True, "") или (False, причина)."""
    for attempt in range(1, max_retries + 1):
        try:
            await send()
            return True, ""
        except TelegramRetryAfter as e:
            logger.warning("Flood control для %d: жду %d сек. (попытка %d/%d)", chat_id, e.retry_after, attempt, max_retries)
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            logger.info("Пользователь %d заблокировал бота", chat_id)
            return False, "blocked"
        except TelegramBadRequest as e:
            logger.warning("Bad request для %d: %s", chat_id, e)
            return False, f"bad_request: {e}"
        except Exception as e:
            logger.error("Неожиданная ошибка для %d: %s", chat_id, e)
            return False, f"error: {e}"
    return False, "flood_control_exhausted"


def write_report(results: list[tuple[int, str | None, str, str]]) -> Path:
    reports_dir = Path("logs")
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"broadcast_debates_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "debate_choice", "status"])
        writer.writerows(results)
    logger.info("Отчет сохранен: %s", report_path)
    return report_path


async def broadcast(args: argparse.Namespace) -> None:
    rows, titles = await load_recipients(args.only)

    # Без ссылки для компании рассылать нельзя
    codes = set(titles) if args.test else {code for _, _, code in rows}
    missing = sorted(code for code in codes if not CHAT_LINKS.get(code))
    if missing:
        logger.error("Нет ссылок в CHAT_LINKS для: %s", ", ".join(missing))
        sys.exit(1)

    for code, title in titles.items():
        if code in codes:
            count = sum(1 for r in rows if r[2] == code)
            logger.info("%s (%s): %d получателей. Текст:\n%s\n", title, code, count, render(title, code))

    config = load_config()
    bot = Bot(token=config.tg_bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        if args.test:
            for code in sorted(codes, key=list(titles).index):
                ok, info = await call_with_retry(args.test, lambda: bot.send_message(args.test, render(titles[code], code)))
                logger.info("Тест %s -> %d: %s", code, args.test, "OK" if ok else info)
            return

        logger.info("Всего получателей: %d", len(rows))
        if args.dry_run:
            for telegram_id, username, code in rows:
                logger.info("  %d @%s -> %s", telegram_id, username or "-", code)
            logger.info("Режим dry-run: сообщения не отправляются")
            return
        if not rows:
            logger.info("Некому отправлять")
            return

        if not args.yes:
            answer = input(f"Отправить сообщение {len(rows)} пользователям? [y/N]: ").strip().lower()
            if answer != "y":
                logger.info("Отменено пользователем")
                return

        delay = 1.0 / args.rate
        results = []
        for i, (telegram_id, username, code) in enumerate(rows, start=1):
            text = render(titles.get(code, code), code)
            ok, info = await call_with_retry(telegram_id, lambda: bot.send_message(telegram_id, text))
            results.append((telegram_id, username, code, "sent" if ok else info))
            logger.info("[%d/%d] %d @%s (%s) -> %s", i, len(rows), telegram_id, username or "-", code, "OK" if ok else info)
            if i < len(rows):
                await asyncio.sleep(delay)
    finally:
        await bot.session.close()

    write_report(results)
    sent = sum(1 for r in results if r[3] == "sent")
    logger.info("Готово: успешно %d/%d", sent, len(results))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Рассылка записавшимся на дебаты ссылок на чаты компаний")
    parser.add_argument("--dry-run", action="store_true", help="Показать получателей и тексты, не отправлять")
    parser.add_argument("--test", type=int, metavar="CHAT_ID", help="Отправить все варианты текста только на этот chat_id")
    parser.add_argument("--only", metavar="CODE", help="Рассылка только одной компании (VTB, AlfaNSeverstal, B1)")
    parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение перед отправкой")
    parser.add_argument(
        "--rate", type=float, default=DEFAULT_RATE_PER_SEC,
        help=f"Сообщений в секунду (по умолчанию {DEFAULT_RATE_PER_SEC}, лимит Telegram ~{MAX_RATE_PER_SEC}/сек)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not (0 < args.rate <= MAX_RATE_PER_SEC):
        logger.error("--rate должен быть в диапазоне (0, %d]", MAX_RATE_PER_SEC)
        sys.exit(1)
    asyncio.run(broadcast(args))


if __name__ == "__main__":
    main()
