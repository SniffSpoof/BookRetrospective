import asyncio
import nest_asyncio

import logging
import argparse
import os
import time

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import BaseFilter
from aiogram import BaseMiddleware

from difflib import get_close_matches
from typing import List, Dict, Any
from typing import Callable, Awaitable

from google.api_core import exceptions
import google.generativeai as genai

from responses_templates import PROMPT, book_prompts, help_text

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Parse command-line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Telegram bot settings")
    parser.add_argument('--telegram-token', type=str, required=True, help="Your Telegram API token")
    parser.add_argument('--gemini-api-keys', nargs='+', required=True, help="List of API keys to use")
    args = parser.parse_args()

    if not args.telegram_token or not all(args.gemini_api_keys):
        raise ValueError("Invalid API keys or token provided")

    return args

args = parse_args()
API_TOKEN = args.telegram_token
API_KEYS = args.gemini_api_keys

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
storage = MemoryStorage()

# Define FSM states
class QuestionState(StatesGroup):
    waiting_for_book = State()
    waiting_for_question = State()

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

# Class to handle Gemini API requests
class GeminiHandler:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.index = 0
        self.configure_model()

    def configure_model(self):
        genai.configure(api_key=self.api_keys[self.index])
        self.model = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21")

    async def generate_response(self, book: str, question: str):
        for _ in range(len(self.api_keys)):  # Iterate through API keys in case of failure
            try:
                response = await asyncio.to_thread(
                    self.model.generate_content, PROMPT.format(book=book, question=question, context="Find in web")
                )
                return response.text
            except exceptions.GoogleAPIError as e:
                logging.warning(f"API key {self.api_keys[self.index]} failed: {e}")
                self.index = (self.index + 1) % len(self.api_keys)
                self.configure_model()

        return "Ошибка при получении ответа. Попробуйте позже."

# Instantiate Gemini handler
gemini_handler = GeminiHandler(API_KEYS)

# Command handlers
@dp.message(Command("start"), RateLimiter(limit=3, period=60))
async def send_welcome(message: Message):
    try:
        book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
        await message.answer(f"📚 Доступные книги:\n\n{book_list_markdown}", parse_mode="Markdown")
        logging.info("/start handled")
    except Exception as e:
        logging.exception(f"Error in /start: {e}")

@dp.message(Command("question"), RateLimiter(limit=3, period=60))
async def ask_book(message: types.Message, state: FSMContext):
    try:
        book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
        await message.answer(f"Введите название книги:\n\nНапример:\n{book_list_markdown}", parse_mode="Markdown")
        await state.set_state(QuestionState.waiting_for_book)
        logging.info("/question handled")
    except Exception as e:
        logging.exception(f"Error in /question: {e}")

@dp.message(QuestionState.waiting_for_book, RateLimiter(limit=3, period=60))
async def save_book(message: types.Message, state: FSMContext):
    try:
        book_input = message.text.strip()
        closest_match = get_close_matches(book_input, book_prompts.keys(), n=1, cutoff=0.7)
        if not closest_match:
            await message.answer("Книга отсутствует в списке доступных.")
            await state.clear()
            return

        book_key = closest_match[0]
        await state.update_data(book=book_key)
        await message.answer(f"Теперь введите ваш вопрос:\n{book_prompts[book_key]}")
        await state.set_state(QuestionState.waiting_for_question)
        logging.info(f"Book selected: {book_key}")
    except Exception as e:
        logging.exception(f"Error in save_book: {e}")

@dp.message(QuestionState.waiting_for_question, RateLimiter(limit=3, period=60))
async def save_question(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        book = user_data.get("book")
        if not book:
            await message.answer("❌ Сессия устарела. Начните заново с /question")
            await state.clear()
            return

        question = message.text.strip()
        if len(question) > 1000:
            await message.answer("❌ Вопрос слишком длинный. Максимум 1000 символов.")
            await state.clear()
            return

        logging.info(f"User {message.from_user.id} asked: {question[:100]}... about {book}")

        await message.answer(f"⏳ Ваш вопрос обрабатывается...")

        response = await gemini_handler.generate_response(book, question)

        if not response or len(response) > 4000:
            response = "⚠️ Не удалось получить корректный ответ. Попробуйте переформулировать вопрос."
        try:
            await message.answer(f"📚 Ответ по книге *{book}*:\n\n{response}", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error for user {message.from_user.id}: {str(e)}\nParse mode set 'HTML'")
            await message.answer(f"📚 Ответ по книге <b>{book}</b>:\n\n{response}", parse_mode="HTML")

    except Exception as e:
        logging.error(f"Error for user {message.from_user.id}: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при обработке вашего вопроса.")
    finally:
        await state.clear()

@dp.message(Command("help"), RateLimiter(limit=3, period=60))
async def send_help(message: Message):
    try:
        await message.answer(help_text)
        logging.info("/help handled")
    except Exception as e:
        logging.exception(f"Error in /help: {e}")

@dp.message(Command("stop"), RateLimiter(limit=3, period=60))
async def stop_bot(message: Message):
    try:
        await message.answer("Бот завершает работу. До свидания!")
        await dp.stop_polling()
        logging.info("Bot stopped")
    except Exception as e:
        logging.exception(f"Error in /stop: {e}")


async def main():
    try:
        logging.info("Starting bot...")
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception(f"Error in main loop: {e}")
    finally:
        await bot.session.close()
        logging.info("Bot has shut down")

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
