from aiogram import types, Bot
from aiogram_dialog.api.exceptions import UnknownIntent
from aiogram.types import ErrorEvent
from aiogram_dialog import DialogManager
from utils.logging_config import log_error

async def dialog_error_handler(event: ErrorEvent):
    """Обработчик ошибок диалогов"""
    exception = event.exception
    
    # Получаем user_id из разных типов событий
    user_id = None
    if event.update.message and event.update.message.from_user:
        user_id = event.update.message.from_user.id
    elif event.update.callback_query and event.update.callback_query.from_user:
        user_id = event.update.callback_query.from_user.id
    elif event.update.inline_query and event.update.inline_query.from_user:
        user_id = event.update.inline_query.from_user.id
    
    # Логируем ошибку
    log_error(exception, f"Ошибка в диалоге", user_id=user_id)
    
    try:
        if isinstance(exception, UnknownIntent):
            message_text = "Упс! Что-то сломалось. К сожалению, текущие данные потеряны. Для продолжения работы нажмите /start"
        else:
            message_text = "Упс! Что-то сломалось попробуйте еще раз. Если бот не работает как надо нажмите /start чтобы начать сначала и вернуться в главное меню. \n\nТех. поддержка @zobko"
        
        # Отправляем сообщение пользователю
        if event.update.message:
            await event.update.message.answer(message_text)
        elif event.update.callback_query:
            await event.update.callback_query.message.answer(message_text)
            await event.update.callback_query.answer()
            
    except Exception as e:
        # Если не удалось отправить сообщение, логируем это
        log_error(e, "Не удалось отправить сообщение об ошибке пользователю")
