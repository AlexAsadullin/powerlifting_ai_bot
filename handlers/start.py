from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from database import Session
from models.models import Student
from handlers.admin import is_admin, get_admin_menu

router = Router()

# Функция для создания inline-клавиатуры
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Занятия с тренером"), KeyboardButton(text="График тренировок")],
            [KeyboardButton(text="Программа тренировок"), KeyboardButton(text="Питание")],
            [KeyboardButton(text="Прогресс"), KeyboardButton(text="База знаний")]
        ],
        resize_keyboard=True,  # Adjusts keyboard size to fit the screen
        one_time_keyboard=False  # Keyboard persists after interaction
    )
    return keyboard

@router.message(Command("start"))
async def start_command(message: types.Message):
    session = Session()
    try:
        if is_admin(str(message.from_user.id)):
            await message.reply(f"Привет, {message.from_user.first_name}! Выбери команду", reply_markup=get_admin_menu())
            return
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

@router.message(F.text == "Админ-панель")
async def handle_admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только тренеру.")
        return
    await message.answer("Добро пожаловать в админ-панель:", reply_markup=get_admin_menu())

@router.message(F.text == "Занятия с тренером")
async def handle_trainer_sessions(message: types.Message):
    await message.answer("Вы выбрали: Занятия с тренером. Напишите, что вас интересует.")


@router.message(F.text == "График тренировок")
async def handle_training_schedule(message: types.Message):
    await message.answer("Вы выбрали: График тренировок. Вот доступное расписание...")


@router.message(F.text == "Программа тренировок")
async def handle_training_program(message: types.Message):
    await message.answer("Вы выбрали: Программа тренировок. Вот ваша программа...")


@router.message(F.text == "Питание")
async def handle_nutrition(message: types.Message):
    await message.answer("Вы выбрали: Питание. Расскажите больше, чтобы я помог составить рацион.")


@router.message(F.text == "Прогресс")
async def handle_progress(message: types.Message):
    await message.answer("Вы выбрали: Прогресс. Вот ваши последние результаты...")


@router.message(F.text == "База знаний")
async def handle_knowledge_base(message: types.Message):
    await message.answer("Вы выбрали: База знаний. Вот полезные материалы для вас...")
