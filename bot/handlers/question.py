from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from difflib import get_close_matches
from bot.states import QuestionState
from bot.gemini_handler import GeminiHandler
from aiogram.types import CallbackQuery
from bot.middlewares import RateLimiter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

from responses_templates import book_prompts, PROMPT

from bot.config import parse_args
args = parse_args()
api_keys = args.gemini_api_keys
gemini_handler = GeminiHandler(api_keys)

app_password = args.gmail_app_password

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = args.gmail_login  # Gmail login
SENDER_PASSWORD = app_password  # Gmail App Password
RECEIVER_EMAIL = args.receivers_email

import logging

question_router = Router()

def create_navigation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="go_back"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def create_rating_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📖 Продолжить по книге", callback_data="continue_book")],
        [
            InlineKeyboardButton(text="1", callback_data="rate_1"),
            InlineKeyboardButton(text="2", callback_data="rate_2"),
            InlineKeyboardButton(text="3", callback_data="rate_3"),
            InlineKeyboardButton(text="4", callback_data="rate_4"),
            InlineKeyboardButton(text="5", callback_data="rate_5"),
        ],
        [InlineKeyboardButton(text="📝 Оставить комментарий", callback_data="add_comment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
        # await state.clear()
        pass

@question_router.callback_query(F.data == "continue_book")
async def handle_continue_book(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    book = user_data.get("book")

    if not book:
        await callback.message.answer("❌ Ошибка: книга не найдена в сессии. Начните заново с /question")
        await state.clear()
        return

    await callback.message.answer(
        f"Введите ваш новый вопрос по книге *{book}*:",
        parse_mode="Markdown",
        reply_markup=create_navigation_keyboard()
    )
    await state.set_state(QuestionState.waiting_for_question)
    await callback.answer()

@question_router.callback_query(F.data.startswith("rate_"))
async def handle_rating(callback: CallbackQuery, state: FSMContext):
    rating = int(callback.data.split("_")[1])
    await state.update_data(rating=rating)

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Оставить комментарий", callback_data="add_comment")],
                [InlineKeyboardButton(text="✅ Завершить оценку", callback_data="finish_rating")]
            ]
        )
    )
    await callback.answer(f"Вы поставили оценку {rating}. Теперь вы можете оставить комментарий или завершить.")


@question_router.callback_query(F.data == "add_comment")
async def handle_add_comment(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Пожалуйста, напишите ваш комментарий:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_comment")]]
        )
    )
    await state.set_state(QuestionState.waiting_for_comment)
    await callback.answer()


@question_router.callback_query(F.data == "cancel_comment")
async def handle_cancel_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback.message.edit_text("❌ Комментарий не был сохранен")
    await callback.answer()
    await handle_finish_rating(callback, state)


@question_router.callback_query(F.data == "finish_rating")
async def handle_finish_rating(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    await save_feedback_to_file(user_data)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Спасибо за ваш отзыв!")
    await state.clear()


@question_router.message(QuestionState.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    user_data = await state.get_data()
    await save_feedback_to_file(user_data)
    await message.answer("✅ Комментарий сохранен! Спасибо за ваш отзыв!")
    await state.clear()


async def save_feedback_to_file(user_data: dict):
    rating = user_data.get("rating", "Без оценки")
    book = user_data.get("book")
    question = user_data.get("question")
    response = user_data.get("response")
    comment = user_data.get("comment", "Без комментария")

    with open("ratings.txt", "a", encoding="utf-8") as file:
        file.write(
            f"Книга: {book}\n"
            f"Вопрос: {question}\n"
            f"Ответ: {response}\n"
            f"Оценка: {rating}\n"
            f"Комментарий: {comment}\n"
            f"-----------------------------\n"
        )

    if comment != "Без комментария":
        await send_email(book, question, response, rating, comment)


async def send_email(book, question, response, rating, comment):
    subject = f"Новый отзыв на книгу: {book}"
    body = (
        f"Книга: {book}\n"
        f"Вопрос: {question}\n"
        f"Ответ: {response}\n"
        f"Оценка: {rating}\n"
        f"Комментарий: {comment}\n"
    )

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_smtp_email, msg)
        logging.info("Email send succefully")
    except Exception as e:
        logging.error(f"Error occured while sending email: {e}")

def send_smtp_email(msg):
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())


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
