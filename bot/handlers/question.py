from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from difflib import get_close_matches
from bot.states import QuestionState
from bot.gemini_handler import GeminiHandler
from aiogram.types import CallbackQuery
from bot.middlewares import RateLimiter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from responses_templates import book_prompts, PROMPT

from bot.config import parse_args
args = parse_args()
api_keys = args.gemini_api_keys
gemini_handler = GeminiHandler(api_keys)

import logging

question_router = Router()

def create_navigation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="go_back"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def create_rating_keyboard():
    buttons = [
        InlineKeyboardButton(text="1", callback_data="rate_1"),
        InlineKeyboardButton(text="2", callback_data="rate_2"),
        InlineKeyboardButton(text="3", callback_data="rate_3"),
        InlineKeyboardButton(text="4", callback_data="rate_4"),
        InlineKeyboardButton(text="5", callback_data="rate_5"),
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    return keyboard

@question_router.message(Command("question"), RateLimiter(limit=5, period=60))
async def ask_book(message: types.Message, state: FSMContext):
    try:
        book_list_markdown = "\n".join(f"- {book}" for book in book_prompts.keys())
        await message.answer(f"Введите название книги:\n\nНапример:\n{book_list_markdown}", reply_markup=create_navigation_keyboard(), parse_mode="Markdown")
        await state.set_state(QuestionState.waiting_for_book)
        logging.info("/question handled")
    except Exception as e:
        logging.exception(f"Error in /question: {e}")

@question_router.message(QuestionState.waiting_for_book, RateLimiter(limit=5, period=60))
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
        await message.answer(f"Теперь введите ваш вопрос:\n{book_prompts[book_key]}", reply_markup=create_navigation_keyboard())
        await state.set_state(QuestionState.waiting_for_question)
        logging.info(f"Book selected: {book_key}")
    except Exception as e:
        logging.exception(f"Error in save_book: {e}")

@question_router.message(QuestionState.waiting_for_question, RateLimiter(limit=5, period=60))
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
        await state.update_data(question=question, response=response)

        if not response or len(response) > 4000:
            response = "⚠️ Не удалось получить корректный ответ. Попробуйте переформулировать вопрос."

        try:
            await message.answer(
                f"📚 Ответ по книге *{book}*:\n\n{response}\n\nПоставить оценку ответу:",
                parse_mode="Markdown",
                reply_markup=create_rating_keyboard()
            )
        except Exception as e:
            logging.error(f"Error for user {message.from_user.id}: {str(e)}\nParse mode set 'HTML'")
            await message.answer(
                f"📚 Ответ по книге <b>{book}</b>:\n\n{response}\n\nПоставить оценку ответу:",
                parse_mode="HTML",
                reply_markup=create_rating_keyboard()
            )

    except Exception as e:
        logging.error(f"Error for user {message.from_user.id}: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при обработке вашего вопроса.")
    finally:
        #await state.clear()
        pass

@question_router.callback_query(F.data.startswith("rate_"))
async def handle_rating(callback: CallbackQuery, state: FSMContext):
    rating = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    user_data = await state.get_data()
    book = user_data.get("book", "Неизвестная книга")
    question = user_data.get("question", "Неизвестный вопрос")
    response = user_data.get("response", "Неизвестный ответ")

    logging.info(f"User {user_id} rated the response: {rating}")

    with open("ratings.txt", "a", encoding="utf-8") as file:
        file.write(
            f"Книга: {book}\n"
            f"Вопрос: {question}\n"
            f"Ответ: {response}\n"
            f"Оценка: {rating}\n"
            f"-----------------------------\n"
        )

    await callback.answer(f"Спасибо за оценку: {rating}!", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()


@question_router.callback_query(lambda c: c.data == "go_back")
async def callback_go_back(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    if "book" in user_data:
        await callback.message.edit_text("🔙 Вы вернулись назад. Введите название книги снова:")
        await state.set_state(QuestionState.waiting_for_book)
    else:
        await callback.message.edit_text("❌ Действие отменено.")
        await state.clear()


@question_router.callback_query(lambda c: c.data == "cancel")
async def callback_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено. Можете начать заново с /question")
