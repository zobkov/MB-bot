from aiogram.filters.state import State, StatesGroup


class MainParticipantSG(StatesGroup):
    """Главное меню участника топ-115"""
    main = State()
    support = State()
    debates = State()          # Запись на дебаты
    debates_confirm = State()  # Подтверждение смены компании


class GuestSG(StatesGroup):
    """Главное меню гостя (роль по умолчанию)"""
    main = State()
    support = State()
