import asyncio
import nest_asyncio
import logging
from aiogram import Bot, Dispatcher
from bot.config import parse_args
from bot.middlewares import RateLimiter, ErrorHandlerMiddleware
from bot.handlers import basic, question

from aiogram import Router, types, F
from aiogram.filters import Command
from bot.states import QuestionState
from bot.middlewares import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

args = parse_args()
bot = Bot(token=args.telegram_token)
dp = Dispatcher()

dp.message.middleware(ErrorHandlerMiddleware())

dp.include_router(basic.basic_router)
dp.include_router(question.question_router)

@dp.message(Command("stop"), RateLimiter(limit=3, period=60))
async def stop_bot(message: types.Message):
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
