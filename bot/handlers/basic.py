from aiogram import Router, types, F
from aiogram.filters import Command
from bot.states import QuestionState
from bot.middlewares import RateLimiter

from responses_templates import book_prompts, help_text, start_text

import logging

basic_router = Router()

# Command handlers
@basic_router.message(Command("start"), RateLimiter(limit=3, period=60))
async def send_welcome(message: types.Message):
    try:
        book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
        await message.answer(start_text+f"\n📚 Доступные книги:\n\n{book_list_markdown}", parse_mode="Markdown")
        logging.info("/start handled")
    except Exception as e:
        logging.exception(f"Error in /start: {e}")

@basic_router.message(Command("help"), RateLimiter(limit=3, period=60))
async def send_help(message: types.Message):
    try:
        await message.answer(help_text)
        logging.info("/help handled")
    except Exception as e:
        logging.exception(f"Error in /help: {e}")
