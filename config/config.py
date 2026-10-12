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
class ConferenceConfig:
    support_contact: str
    tech_contact: str
    debate_companies: list[DebateCompany]
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
