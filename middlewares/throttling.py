from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from cachetools import TTLCache


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        self.limit = limit
        # TTLCache сам удалит ключ через ttl секунд
        self.users: TTLCache = TTLCache(maxsize=1000, ttl=limit)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:

        user_id = None

        # ✅ Явная проверка типа события
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            # ✅ Элегантная логика кэша
            if user_id in self.users:
                return  # Просто игнорируем спам

            # Сохраняем любой флаг (True), кэш сам позаботится о времени жизни
            self.users[user_id] = True

        return await handler(event, data)
