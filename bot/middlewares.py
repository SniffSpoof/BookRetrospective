import time
import logging
from typing import Dict, Any, Callable, Awaitable
from aiogram.filters import BaseFilter
from aiogram import BaseMiddleware
from aiogram.types import Message

import logging

# Define RateLimiter filter
class RateLimiter(BaseFilter):
    def __init__(self, limit: int = 1, period: int = 5):
        self.limit = limit
        self.period = period
        self.users = {}

    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        now = time.time()

        if user_id not in self.users:
            self.users[user_id] = [now]
            return True

        timestamps = [t for t in self.users[user_id] if now - t < self.period]
        if len(timestamps) < self.limit:
            timestamps.append(now)
            self.users[user_id] = timestamps
            return True

        await message.answer(f"⚠️ Слишком много запросов. Подождите {self.period} секунд.")
        return False

# Define Error handler
class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            logging.exception(f"Unhandled exception: {e}")
            await event.answer("⚠️ Произошла непредвиденная ошибка. Попробуйте позже.")
            return None
