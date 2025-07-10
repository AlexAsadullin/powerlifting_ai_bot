from aiogram import Dispatcher, types
from database import Session
from models.users import Student

async def start_command(message: types.Message):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            # Создание нового студента
            student = Student(
                telegram_id=str(message.from_user.id),
                username=message.from_user.username,
                name=message.from_user.first_name
            )
            session.add(student)
            session.commit()
        await message.reply(f"Привет, {student.name}! Я  Руслана Сидорова для персональных тренировок. Напиши /start чтобы начать.")
    finally:
        session.close()

def register_handlers(dp: Dispatcher):
    dp.message(commands=['start'])(start_command)