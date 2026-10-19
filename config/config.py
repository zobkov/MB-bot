import csv
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from environs import Env

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class DatabaseConfig:
    user: str
    password: str
    database: str
    host: str
    port: int = 5432


@dataclass
class RedisConfig:
    password: Optional[str]
    host: str = "localhost"
    port: int = 6379


@dataclass
class TgBot:
    token: str


@dataclass
class DebateCompany:
    code: str       # алиас для экспорта (VTB, AlfaNSeverstal, B1)
    title: str      # название для пользователя
    capacity: int


@dataclass
class OpenEvent:
    code: str         # алиас для экспорта (CPS, Lotakov, ...)
    title: str        # название в тексте списка мероприятий и окна отмены
    schedule: str     # дата и время текстом
    description: str  # текст карточки мероприятия, HTML (<b>, <i>; & и < экранировать)
    capacity: int
    alias: str = ""   # короткое название для кнопки в списке; пусто — используется title


@dataclass
class ProgramItem:
    code: str         # уникальный во всей программе; у мероприятий с записью — алиас для экспорта
    alias: str        # короткое название для кнопки (параллельные мероприятия стоят в одной строке)
    title: str        # полное название: расписание дня и карточка
    time: str         # время текстом, может быть пустым
    place: str        # аудитория, может быть пустой
    description: str  # текст карточки, HTML (<b>, <i>; & и < экранировать)
    # Слот записи на параллельные мероприятия: в одном слоте — одна запись на человека.
    # Пусто — мероприятие без записи.
    slot: str = ""
    capacity: int = 0
    # Показывать в карточке, на какую компанию дебатов записан участник
    show_debate_choice: bool = False


@dataclass
class ProgramDay:
    code: str
    title: str  # заголовок окна и текст кнопки дня
    date: str   # дата для карточки мероприятия
    items: list[ProgramItem] = field(default_factory=list)


@dataclass
class Program:
    """Программа для участников топ-115 (config/program.json)"""
    days: list[ProgramDay] = field(default_factory=list)

    def get_day(self, code: str) -> Optional[ProgramDay]:
        return next((d for d in self.days if d.code == code), None)

    def get_item(self, code: str) -> Optional[tuple[ProgramDay, ProgramItem]]:
        for day in self.days:
            for item in day.items:
                if item.code == code:
                    return day, item
        return None

    @property
    def parallel_items(self) -> list[ProgramItem]:
        """Мероприятия с записью, в порядке программы"""
        return [item for day in self.days for item in day.items if item.slot]


@dataclass
class ConferenceConfig:
    support_contact: str
    tech_contact: str
    debate_companies: list[DebateCompany]
    # Открытые мероприятия (запись гостей), порядок — как в конфиге
    open_events: list[OpenEvent] = field(default_factory=list)
    program: Program = field(default_factory=Program)
    # Ники топ-115 в нижнем регистре и без @
    main_usernames: set[str] = field(default_factory=set)
    # user_id участников топ-115 без username
    main_user_ids: set[int] = field(default_factory=set)


@dataclass
class Config:
    tg_bot: TgBot
    db: DatabaseConfig
    redis: RedisConfig
    conference: ConferenceConfig
    admin_ids: list[int] = field(default_factory=list)
    admin_notification_ids: list[int] = field(default_factory=list)
    log_level: str = "INFO"


def normalize_username(username: Optional[str]) -> Optional[str]:
    """Приводит username к виду для сравнения: без @, пробелов и в нижнем регистре"""
    if not username:
        return None
    username = username.strip().lstrip("@").strip().lower()
    return username or None


def _parse_ids(raw: str) -> list[int]:
    ids = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))
    return ids


def _load_main_usernames(csv_path: str) -> set[str]:
    """Загружает ники топ-115 из CSV (колонка username)"""
    path = csv_path if os.path.isabs(csv_path) else os.path.join(PROJECT_ROOT, csv_path)
    usernames = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            username = normalize_username(row.get("username"))
            if username:
                usernames.add(username)
    logger.info(f"Загружено {len(usernames)} ников топ-115 из {path}")
    return usernames


def _load_program(path: str) -> Program:
    """Загружает программу из program.json. Коды мероприятий — id кнопок и ключи в БД, поэтому уникальны."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    days = [
        ProgramDay(
            code=d["code"],
            title=d["title"],
            date=d["date"],
            items=[ProgramItem(**item) for item in d.get("items", [])],
        )
        for d in raw.get("days", [])
    ]

    codes = [d.code for d in days] + [item.code for d in days for item in d.items]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        raise ValueError(f"Повторяющиеся коды в программе: {', '.join(sorted(duplicates))}")
    for d in days:
        for item in d.items:
            if item.slot and item.capacity <= 0:
                raise ValueError(f"У мероприятия с записью {item.code} не указана вместимость")

    program = Program(days=days)
    logger.info(f"Загружена программа: {len(days)} дн., мероприятий с записью — {len(program.parallel_items)}")
    return program


def load_config(path: str = None) -> Config:
    # Загружаем JSON конфигурацию (несекретные данные)
    config_path = path or os.path.join(os.path.dirname(__file__), "conference_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        json_config = json.load(f)

    # Загружаем переменные окружения для секретных данных
    env = Env()
    env.read_env()

    tg_bot = TgBot(token=env.str("BOT_TOKEN"))
    db_config = DatabaseConfig(
        user=env.str("DB_USER"),
        password=env.str("DB_PASS"),
        database=env.str("DB_NAME"),
        host=env.str("DB_HOST"),
        port=env.int("DB_PORT", 5432),
    )

    redis = RedisConfig(
        host=env.str("REDIS_HOST", "localhost"),
        port=env.int("REDIS_PORT", 6379),
        password=env.str("REDIS_PASSWORD", None) if env.str("REDIS_PASSWORD", "") else None,
    )

    participants = json_config.get("main_participants", {})
    conference = ConferenceConfig(
        support_contact=json_config.get("support_contact", "@mbconf_support"),
        tech_contact=json_config.get("tech_contact", "@zobko"),
        debate_companies=[DebateCompany(**c) for c in json_config.get("debate_companies", [])],
        open_events=[OpenEvent(**e) for e in json_config.get("open_events", [])],
        program=_load_program(os.path.join(os.path.dirname(config_path), "program.json")),
        main_usernames=_load_main_usernames(participants.get("usernames_csv", "115users.csv")),
        main_user_ids={int(i) for i in participants.get("extra_user_ids", [])},
    )

    return Config(
        tg_bot=tg_bot,
        db=db_config,
        redis=redis,
        conference=conference,
        admin_ids=_parse_ids(env.str("ADMIN_IDS", "")),
        admin_notification_ids=_parse_ids(env.str("ADMIN_NOTIFICATION", "")),
        log_level=env.str("LOG_LEVEL", "INFO"),
    )
