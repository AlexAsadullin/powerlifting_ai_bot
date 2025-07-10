from aiogram import Dispatcher, types
from database import Session
from models.user import User

async def start_command(message: types.Message):
    session = Session()
    try:
        # Проверка, есть ли пользователь в БД
        user = session.query(User).filter_by(telegram_id=str(message.from_user.id)).first()
        if not user:
            # Создание нового пользователя
            user = User(telegram_id=str(message.from_user.id), name=message.from_user.first_name)
            session.add(user)
            session.commit()
        await message.reply(f"Привет, {user.name}! Я бот для персональных тренировок. Напиши /start для начала.")
    finally:
        session.close()

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(start_command, commands=['start'])