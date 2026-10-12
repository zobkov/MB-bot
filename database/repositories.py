from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import DebateCompany as DebateCompanyConfig
from database.models import ROLE_GUEST, ROLE_MAIN, DebateCompany, DebateRegistration, Setting, User
from utils.logging_config import log_db_operation, log_error


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_user(self, telegram_id: int, telegram_username: Optional[str], is_main_participant: bool) -> User:
        """Создать пользователя или обновить его username, затем назначить роль топ-115, если он есть в списке.
        INSERT ... ON CONFLICT защищает от гонки при одновременных первых нажатиях."""
        try:
            stmt = (
                pg_insert(User)
                .values(telegram_id=telegram_id, telegram_username=telegram_username, role=ROLE_GUEST)
                .on_conflict_do_update(
                    index_elements=[User.telegram_id],
                    set_={"telegram_username": telegram_username},
                )
                .returning(User.id)
            )
            await self.session.execute(stmt)
            await self.session.commit()

            user = await self.get_user_by_telegram_id(telegram_id)

            # Только повышение guest -> main: понижение делается вручную через /role
            if is_main_participant and not user.role_overridden and user.role != ROLE_MAIN:
                user.role = ROLE_MAIN
                await self.session.commit()
                log_db_operation("UPDATE", "conf_users", "role set to main (top-115 list)", telegram_id)

            log_db_operation("UPSERT", "conf_users", f"username={telegram_username} role={user.role}", telegram_id)
            return user
        except Exception as e:
            await self.session.rollback()
            log_error(e, "Ошибка при создании/обновлении пользователя", telegram_id)
            raise

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(func.lower(User.telegram_username) == username.lower())
        )
        return result.scalars().first()

    async def set_role(self, telegram_id: int, role: str) -> Optional[User]:
        """Ручная смена роли (админская команда /role)"""
        user = await self.get_user_by_telegram_id(telegram_id)
        if user is None:
            return None
        user.role = role
        user.role_overridden = True
        await self.session.commit()
        log_db_operation("UPDATE", "conf_users", f"role manually set to {role}", telegram_id)
        return user


class SettingsRepository:
    DEBATES_OPEN = "debates_open"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_bool(self, key: str, default: bool = False) -> bool:
        result = await self.session.execute(select(Setting.value).where(Setting.key == key))
        value = result.scalar_one_or_none()
        if value is None:
            return default
        return value == "1"

    async def set_bool(self, key: str, value: bool) -> None:
        raw = "1" if value else "0"
        stmt = (
            pg_insert(Setting)
            .values(key=key, value=raw)
            .on_conflict_do_update(index_elements=[Setting.key], set_={"value": raw, "updated_at": func.now()})
        )
        await self.session.execute(stmt)
        await self.session.commit()
        log_db_operation("UPDATE", "conf_settings", f"{key}={raw}")


@dataclass
class CompanySeats:
    code: str
    title: str
    capacity: int
    taken: int

    @property
    def free(self) -> int:
        return max(self.capacity - self.taken, 0)


class RegisterResult(Enum):
    OK = "ok"
    SAME = "same"        # пользователь уже записан на эту компанию
    FULL = "full"        # мест нет
    UNKNOWN = "unknown"  # такой компании нет


class DebateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def sync_companies(self, companies: list[DebateCompanyConfig]) -> None:
        """Синхронизирует список компаний и вместимость с конфигом"""
        for order, company in enumerate(companies):
            stmt = (
                pg_insert(DebateCompany)
                .values(code=company.code, title=company.title, capacity=company.capacity, sort_order=order)
                .on_conflict_do_update(
                    index_elements=[DebateCompany.code],
                    set_={"title": company.title, "capacity": company.capacity, "sort_order": order},
                )
            )
            await self.session.execute(stmt)
        await self.session.commit()
        log_db_operation("SYNC", "conf_debate_companies", f"{len(companies)} companies")

    async def get_seats(self) -> list[CompanySeats]:
        taken = (
            select(DebateRegistration.company_code, func.count().label("taken"))
            .group_by(DebateRegistration.company_code)
            .subquery()
        )
        result = await self.session.execute(
            select(DebateCompany.code, DebateCompany.title, DebateCompany.capacity, func.coalesce(taken.c.taken, 0))
            .outerjoin(taken, taken.c.company_code == DebateCompany.code)
            .order_by(DebateCompany.sort_order)
        )
        return [CompanySeats(code=r[0], title=r[1], capacity=r[2], taken=r[3]) for r in result.all()]

    async def get_user_choice(self, user_id: int) -> Optional[str]:
        result = await self.session.execute(
            select(DebateRegistration.company_code).where(DebateRegistration.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def register(self, user_id: int, company_code: str) -> RegisterResult:
        """Записать пользователя на компанию (или сменить запись) в одной транзакции.

        Защита от гонок:
        - строка компании блокируется SELECT ... FOR UPDATE, поэтому проверка «есть ли место» и вставка
          для одной компании выполняются строго по очереди — вместимость не может быть превышена;
        - запись пользователя тоже блокируется, а вставка идет через ON CONFLICT (user_id), поэтому
          двойные нажатия одного пользователя не создают дублей.
        Порядок блокировок всегда «компания -> запись пользователя», дедлоков нет.
        """
        try:
            company = (
                await self.session.execute(
                    select(DebateCompany).where(DebateCompany.code == company_code).with_for_update()
                )
            ).scalar_one_or_none()
            if company is None:
                await self.session.rollback()
                return RegisterResult.UNKNOWN

            current = (
                await self.session.execute(
                    select(DebateRegistration.company_code)
                    .where(DebateRegistration.user_id == user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if current == company_code:
                await self.session.rollback()
                return RegisterResult.SAME

            taken = (
                await self.session.execute(
                    select(func.count()).select_from(DebateRegistration)
                    .where(DebateRegistration.company_code == company_code)
                )
            ).scalar_one()
            if taken >= company.capacity:
                await self.session.rollback()
                return RegisterResult.FULL

            stmt = (
                pg_insert(DebateRegistration)
                .values(user_id=user_id, company_code=company_code)
                .on_conflict_do_update(
                    index_elements=[DebateRegistration.user_id],
                    set_={"company_code": company_code, "updated_at": func.now()},
                )
            )
            await self.session.execute(stmt)
            await self.session.commit()
            log_db_operation("UPSERT", "conf_debate_registrations", f"{current} -> {company_code}", user_id)
            return RegisterResult.OK
        except Exception as e:
            await self.session.rollback()
            log_error(e, "Ошибка при записи на дебаты", user_id)
            raise

    async def cancel(self, user_id: int) -> Optional[str]:
        """Удалить запись пользователя на дебаты. Возвращает код компании или None, если записи не было.
        Удаление только освобождает место, поэтому блокировка компании не нужна."""
        try:
            result = await self.session.execute(
                delete(DebateRegistration)
                .where(DebateRegistration.user_id == user_id)
                .returning(DebateRegistration.company_code)
            )
            code = result.scalar_one_or_none()
            await self.session.commit()
            if code:
                log_db_operation("DELETE", "conf_debate_registrations", f"{code} cancelled", user_id)
            return code
        except Exception as e:
            await self.session.rollback()
            log_error(e, "Ошибка при отмене записи на дебаты", user_id)
            raise

    async def export_rows(self) -> list[tuple[int, Optional[str], str]]:
        """(telegram_id, username, company_code) по всем записям"""
        result = await self.session.execute(
            select(User.telegram_id, User.telegram_username, DebateRegistration.company_code)
            .join(DebateRegistration, DebateRegistration.user_id == User.id)
            .join(DebateCompany, DebateCompany.code == DebateRegistration.company_code)
            .order_by(DebateCompany.sort_order, DebateRegistration.created_at)
        )
        return [tuple(r) for r in result.all()]
