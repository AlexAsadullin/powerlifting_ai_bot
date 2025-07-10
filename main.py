import os
from aiogram import Bot, Dispatcher, executor
from config import BOT_TOKEN
from handlers.start import register_handlers
from database import init_db
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv(BOT_TOKEN)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

if __name__ == '__main__':
    init_db()
    register_handlers(dp)
    executor.start_polling(dp, skip_updates=True)