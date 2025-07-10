from aiogram import Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database import Session
from models.users import Student

router = Router()

# Функция для создания inline-клавиатуры
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Занятия с тренером", callback_data="trainer_sessions")],
        [KeyboardButton(text="График тренировок", callback_data="workout_schedule")],
        [KeyboardButton(text="Программа тренировок", callback_data="workout_program")],
        [KeyboardButton(text="Питание", callback_data="nutrition")],
        [KeyboardButton(text="Прогресс", callback_data="progress")],
        [KeyboardButton(text="База знаний", callback_data="knowledge_base")]
    ])
    return keyboard

@router.message(Command("start"))
async def start_command(message: types.Message):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            # Создание нового ученика
            student = Student(
                telegram_id=str(message.from_user.id),
                username=message.from_user.username,
                name=message.from_user.first_name
            )
            session.add(student)
            session.commit()
        await message.reply(f"Привет, {student.name}! Я телеграм-бот Руслана Сидорова для"
                            f" персональных тренировок. Выбери команду",
                            reply_markup=get_main_menu())
    finally:
        session.close()

# Обработчик нажатий на кнопки
@router.callback_query()
async def handle_button_callback(callback_query: types.CallbackQuery):
    callback_data = callback_query.data
    responses = {
        "trainer_sessions": "Вы выбрали занятия с тренером!",
        "workout_schedule": "Вы выбрали график тренировок!",
        "workout_program": "Вы выбрали программу тренировок!",
        "nutrition": "Вы выбрали питание!",
        "progress": "Вы выбрали прогресс!",
        "knowledge_base": "Вы выбрали базу знаний!"
    }
    response = responses.get(callback_data, "Неизвестная команда")
    await callback_query.message.answer(response)
    await callback_query.answer()  # Подтверждение обработки callback