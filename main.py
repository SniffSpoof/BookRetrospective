from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile
import aiofiles

from difflib import get_close_matches

from typing import List, Dict, Any
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import os
import sys
import time

import asyncio
import nest_asyncio

import logging

import google.generativeai as genai
from google.api_core import exceptions

from groq import Groq

import threading
from queue import Queue, Empty

from responses_templates import PROMPT, book_prompts, help_text
##############
# PARSE ARGS #
##############
import argparse
def parse_args():
    parser = argparse.ArgumentParser(description="Arguments for running the Extra")
    
    parser.add_argument('--telegram-token', type=str, required=True, help="Your Telegram API token")
    parser.add_argument('--gemini-api-keys', nargs='+', required=True, help="List of API keys to use")

    return parser.parse_args()


###############
# GLOBAL VARS #
###############
args = parse_args()

GEMINI_API_KEY = args.gemini_api_keys[0]

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21")

API_KEYS = args.gemini_api_keys

API_TOKEN = args.telegram_token

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


##########
# STATES #
##########
class QuestionStateWithoutFile(StatesGroup):
    waiting_for_book_without_file = State()
    waiting_for_question_without_file = State()


###############
# DISPATCHERS #
###############
@dp.message(Command("start"))
async def send_welcome(message: Message):
    welcome_text = "Доступные книги:\n\n"
    book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
    await message.answer(welcome_text+book_list_markdown, parse_mode="Markdown")

@dp.message(Command("question"))
async def ask_book(message: types.Message, state: FSMContext):
    book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
    await message.answer(
        "Введите название книги:\n\nНапример:\n"+book_list_markdown,
        parse_mode="Markdown")
    await state.set_state(QuestionStateWithoutFile.waiting_for_book_without_file)

@dp.message(QuestionStateWithoutFile.waiting_for_book_without_file)
async def save_book(message: types.Message, state: FSMContext):
    book_input = message.text.strip()
    closest_match = get_close_matches(book_input, book_prompts.keys(), n=1, cutoff=0.7)
    if closest_match:
        book_key = closest_match[0]
        prompts = book_prompts[book_key]
    else:
        await message.answer('Книга отсутствует в списке доступных')
        await state.clear()
        return

    await state.update_data(book=book_key if closest_match else book_input)
    await message.answer(f'Теперь введите ваш вопрос:{prompts}')
    await state.set_state(QuestionStateWithoutFile.waiting_for_question_without_file)

@dp.message(QuestionStateWithoutFile.waiting_for_question_without_file)
async def save_question(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    book = user_data.get("book")
    question = message.text

    await message.answer(f"Ваш вопрос в обработке\n\n📖 Книга: {book}\n❓ Вопрос: {question}")
    await state.clear()

    response = model.generate_content(PROMPT.format(book=book, question=question, context="Find in web")).text
    await message.answer(f"🤖 Ответ: {response}", parse_mode="Markdown")

@dp.message(Command("help"))
async def send_help(message: Message):
    await message.answer(help_text)

@dp.message(Command("stop"))
async def stop_bot(message: Message):
    await message.answer("Бот завершает работу. До свидания!")
    await dp.stop_polling()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
