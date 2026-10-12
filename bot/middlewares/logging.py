from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
import logging

from utils.logging_config import log_user_action, log_error


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования действий пользователей"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем информацию о пользователе
        user = None
        action = ""
        details = ""
        
        if isinstance(event, Message):
            user = event.from_user
            if event.text:
                action = "MESSAGE"
                details = f"text: {event.text[:100]}..."
            elif event.contact:
                action = "CONTACT_SHARED"
                details = f"phone: {event.contact.phone_number}"
            elif event.photo:
                action = "PHOTO_SENT"
                details = f"photo_id: {event.photo[-1].file_id}"
            else:
                action = "MESSAGE_OTHER"
                details = f"content_type: {event.content_type}"
                
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            action = "CALLBACK"
            details = f"data: {event.data}"
            
        # Логируем действие пользователя
        if user:
            username = user.username or f"{user.first_name or ''} {user.last_name or ''}".strip()
            log_user_action(user.id, username, action, details)
        
        # Выполняем обработчик
        try:
            result = await handler(event, data)
            return result
        except Exception as e:
            user_id = user.id if user else None
            handler_name = getattr(handler, '__name__', str(handler))
            log_error(e, f"Ошибка в обработчике {handler_name}", user_id)
            raise
