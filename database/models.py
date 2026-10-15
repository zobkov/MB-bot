from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()

# Роли пользователей
ROLE_MAIN = "main"    # участник топ-115
ROLE_GUEST = "guest"  # гость открытых мероприятий (роль по умолчанию)

# ВАЖНО: БД может быть общей с ботом отбора волонтеров (там уже есть таблица users),
# поэтому все таблицы этого бота имеют префикс conf_.


class User(Base):
    __tablename__ = "conf_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_GUEST, server_default=ROLE_GUEST)
    # Роль выставлена вручную админской командой /role — автоназначение по списку ее не трогает
    role_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    debate_registration: Mapped[Optional["DebateRegistration"]] = relationship(
        "DebateRegistration", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    event_registrations: Mapped[list["EventRegistration"]] = relationship(
        "EventRegistration", back_populates="user", cascade="all, delete-orphan"
    )


class DebateCompany(Base):
    """Компании управленческих дебатов. Строки синхронизируются с conference_config.json при старте.
    Строка компании также служит замком (SELECT ... FOR UPDATE) при записи — см. DebateRepository."""
    __tablename__ = "conf_debate_companies"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class DebateRegistration(Base):
    """Запись на дебаты: не больше одной на пользователя"""
    __tablename__ = "conf_debate_registrations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conf_users.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(50), ForeignKey("conf_debate_companies.code"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="debate_registration")


class OpenEvent(Base):
    """Открытые мероприятия для гостей. Строки синхронизируются с conference_config.json при старте.
    Строка мероприятия также служит замком (SELECT ... FOR UPDATE) при записи — см. EventRepository."""
    __tablename__ = "conf_events"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class EventRegistration(Base):
    """Запись на открытое мероприятие: пользователь может записаться на несколько, но на каждое — один раз"""
    __tablename__ = "conf_event_registrations"
    __table_args__ = (UniqueConstraint("user_id", "event_code", name="uq_conf_event_registrations_user_event"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conf_users.id", ondelete="CASCADE"), nullable=False)
    event_code: Mapped[str] = mapped_column(String(50), ForeignKey("conf_events.code"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="event_registrations")


class Setting(Base):
    """Флаги бота, переключаемые админами без деплоя (например, открытие записи на дебаты)"""
    __tablename__ = "conf_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
