import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logging(log_level: str = "INFO"):
    """Настройка системы логирования"""
    
    # Создаем директорию для логов
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Консольный уровень логирования (по умолчанию INFO)
    console_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Формат логов
    log_format = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Подробный формат для файлов
    detailed_format = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Корневой логгер настраиваем на DEBUG, чтобы файловые хендлеры получали все сообщения
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Очищаем существующие хендлеры
    root_logger.handlers.clear()
    
    # Консольный хендлер - только INFO и выше
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)
    
    # Общий файловый хендлер - DEBUG и выше
    general_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=50*1024*1024,  # 50MB
        backupCount=5,
        encoding='utf-8'
    )
    general_handler.setLevel(logging.DEBUG)
    general_handler.setFormatter(detailed_format)
    root_logger.addHandler(general_handler)
    
    # Хендлер для ошибок
    error_handler = RotatingFileHandler(
        log_dir / "errors.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_format)
    root_logger.addHandler(error_handler)
    
    # Хендлер для действий пользователей - пишет в файл DEBUG и выше
    user_actions_handler = RotatingFileHandler(
        log_dir / "user_actions.log",
        maxBytes=20*1024*1024,  # 20MB
        backupCount=5,
        encoding='utf-8'
    )
    user_actions_handler.setLevel(logging.DEBUG)
    user_actions_handler.setFormatter(detailed_format)
    
    # Создаем специальный логгер для действий пользователей
    user_logger = logging.getLogger('user_actions')
    user_logger.handlers.clear()
    user_logger.addHandler(user_actions_handler)
    user_logger.setLevel(logging.DEBUG)
    user_logger.propagate = False  # Не передаем в корневой логгер
    
    # Логгер для базы данных
    db_handler = RotatingFileHandler(
        log_dir / "database.log",
        maxBytes=20*1024*1024,  # 20MB
        backupCount=3,
        encoding='utf-8'
    )
    db_handler.setLevel(logging.INFO)
    db_handler.setFormatter(detailed_format)
    
    db_logger = logging.getLogger('database')
    db_logger.handlers.clear()
    db_logger.addHandler(db_handler)
    db_logger.setLevel(logging.INFO)
    db_logger.propagate = False
    
    # Понижаем уровень для внешних библиотек
    logging.getLogger('aiogram').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    
    return root_logger


def get_user_logger():
    """Получить логгер для действий пользователей"""
    return logging.getLogger('user_actions')


def get_db_logger():
    """Получить логгер для базы данных"""
    return logging.getLogger('database')


def log_user_action(user_id: int, username: str, action: str, details: str = ""):
    """Логирование действий пользователя (уровень INFO)"""
    logger = get_user_logger()
    logger.info(f"USER:{user_id}:{username} - {action} - {details}")


def log_user_debug(user_id: int, username: str, action: str, details: str = ""):
    """Логирование действий пользователя для отладки (уровень DEBUG в файл)"""
    logger = get_user_logger()
    logger.debug(f"USER:{user_id}:{username} - {action} - {details}")


def log_db_operation(operation: str, table: str, details: str = "", user_id: int = None):
    """Логирование операций с базой данных"""
    logger = get_db_logger()
    user_info = f"USER:{user_id}" if user_id else "SYSTEM"
    logger.info(f"{user_info} - {operation} - {table} - {details}")


def log_error(error: Exception, context: str = "", user_id: int = None):
    """Логирование ошибок"""
    logger = logging.getLogger(__name__)
    user_info = f"USER:{user_id}" if user_id else ""
    logger.error(f"{user_info} - {context} - {type(error).__name__}: {str(error)}", exc_info=True)
