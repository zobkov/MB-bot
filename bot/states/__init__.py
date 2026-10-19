from aiogram.filters.state import State, StatesGroup


class MainParticipantSG(StatesGroup):
    """Главное меню участника топ-115"""
    main = State()
    support = State()
    debates = State()          # Запись на дебаты
    debates_confirm = State()  # Подтверждение смены компании
    program = State()          # Программа: выбор дня
    program_day = State()      # Мероприятия дня
    program_item = State()     # Карточка мероприятия; у параллельных — запись/отмена
    parallel_confirm = State() # Подтверждение смены записи в слоте
    parallel_cancel = State()  # Подтверждение отмены записи


class GuestSG(StatesGroup):
    """Главное меню гостя (роль по умолчанию)"""
    main = State()
    support = State()
    events = State()          # Список открытых мероприятий
    event = State()           # Карточка мероприятия: описание, места, запись/отмена
    event_cancel = State()    # Подтверждение отмены записи
