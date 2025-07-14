from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import time
import datetime
import os
from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from database import Session
from models.models import Student, GroupStudent, PaymentRequest, Trainer, Group, Schedule, Progress
from handlers.admin import is_admin, get_admin_menu

router = Router()


class ProgramSelection(StatesGroup):
    waiting_for_group = State()


class PaymentStates(StatesGroup):
    waiting_for_screenshot = State()
    waiting_for_sessions = State()


class ProgressStates(StatesGroup):
    waiting_for_training_data = State()
    waiting_for_photo = State()


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


def get_progress_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="загрузить тренировку", callback_data="upload_training")],
        [InlineKeyboardButton(text="загрузить фото", callback_data="upload_photo")],
        [InlineKeyboardButton(text="назад", callback_data="back_to_main")]
    ])
    return keyboard


@router.message(Command("start"))
async def start_command(message: types.Message):
    session = Session()
    try:
        if is_admin(str(message.from_user.id)):
            await message.reply(f"Привет, {message.from_user.first_name}! Выбери команду",
                                reply_markup=get_admin_menu())
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


@router.message(F.text == "Занятия с тренером")
async def handle_trainer_sessions(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
        await message.answer(f"У вас осталось {student.remaining_sessions} оплаченных занятий.")
        pending_request = session.query(PaymentRequest).filter_by(student_id=student.id, status='pending').first()
        if pending_request:
            await message.answer(
                f"Ваш запрос на {pending_request.sessions_requested} занятий находится на рассмотрении.")
        else:
            await message.answer("Отправьте файл (например, скриншот или документ) с подтверждением оплаты.")
            await state.set_state(PaymentStates.waiting_for_screenshot)
    finally:
        session.close()


# Updated handler to accept both photos and documents for screenshot
@router.message(F.photo | F.document, PaymentStates.waiting_for_screenshot)
async def handle_screenshot(message: types.Message, state: FSMContext):
    file_id = None
    file_type = None
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = 'photo'
    elif message.document:
        file_id = message.document.file_id
        file_type = 'document'
    await state.update_data(screenshot_file_id=file_id, file_type=file_type)
    await message.answer("Файл получен. Укажите количество занятий, за которые вы оплатили.")
    await state.set_state(PaymentStates.waiting_for_sessions)


# Updated handler to send either photo or document to trainer
@router.message(F.text, PaymentStates.waiting_for_sessions)
async def handle_sessions(message: types.Message, state: FSMContext):
    try:
        sessions = int(message.text)
        if sessions <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите положительное целое число.")
        return
    data = await state.get_data()
    screenshot_file_id = data.get('screenshot_file_id')
    file_type = data.get('file_type')
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        payment_request = PaymentRequest(
            student_id=student.id,
            sessions_requested=sessions,
            status='pending',
            screenshot_file_id=screenshot_file_id,
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now()
        )
        session.add(payment_request)
        session.commit()
        # Notify trainer with appropriate file type
        trainer = session.query(Trainer).first()
        if trainer:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить", callback_data=f"approve_{payment_request.id}"),
                 InlineKeyboardButton(text="Отклонить", callback_data=f"reject_{payment_request.id}")]
            ])
            if file_type == 'photo':
                await message.bot.send_photo(
                    chat_id=trainer.telegram_id,
                    photo=screenshot_file_id,
                    caption=f"Ученик @{student.username} оплатил {sessions} занятий.",
                    reply_markup=keyboard
                )
            else:
                await message.bot.send_document(
                    chat_id=trainer.telegram_id,
                    document=screenshot_file_id,
                    caption=f"Ученик @{student.username} оплатил {sessions} занятий.",
                    reply_markup=keyboard
                )
        await message.answer("Ваш запрос отправлен тренеру на рассмотрение.")
        await state.clear()
    finally:
        session.close()


@router.callback_query(F.data.startswith("approve_"))
async def handle_approve(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав для этого действия.")
        return
    request_id = callback.data.split("_")[1]
    session = Session()
    try:
        payment_request = session.query(PaymentRequest).filter_by(id=request_id).first()
        if not payment_request or payment_request.status != 'pending':
            await callback.answer("Этот запрос уже обработан.")
            return
        student = session.query(Student).filter_by(id=payment_request.student_id).first()
        student.remaining_sessions += payment_request.sessions_requested
        payment_request.status = 'approved'
        payment_request.updated_at = datetime.datetime.now()
        session.commit()
        # Edit the caption of the photo/document message
        await callback.message.edit_caption(
            caption="Платеж одобрен.",
            reply_markup=None
        )
        await callback.bot.send_message(
            chat_id=student.telegram_id,
            text="Ваш платеж одобрен. Количество оплаченных занятий обновлено."
        )
        await callback.answer("Подтверждение выполнено!")
    finally:
        session.close()


# Updated handler to edit caption instead of text for photo/document messages
@router.callback_query(F.data.startswith("reject_"))
async def handle_reject(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав для этого действия.")
        return
    request_id = callback.data.split("_")[1]
    session = Session()
    try:
        payment_request = session.query(PaymentRequest).filter_by(id=request_id).first()
        if not payment_request or payment_request.status != 'pending':
            await callback.answer("Этот запрос уже обработан.")
            return
        payment_request.status = 'rejected'
        payment_request.updated_at = datetime.datetime.now()
        session.commit()
        # Edit the caption of the photo/document message
        await callback.message.edit_caption(
            caption="Платеж отклонен.",
            reply_markup=None
        )
        await callback.bot.send_message(
            chat_id=payment_request.student.telegram_id,
            text="Ваш платеж отклонен."
        )
        await callback.answer("Отклонение выполнено!")
    finally:
        session.close()


# Updated handler to display training schedules for student's groups
@router.message(F.text == "График тренировок")
async def handle_training_schedule(message: types.Message):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
        # Query groups through GroupStudent junction table
        groups = session.query(Group).join(GroupStudent).filter(GroupStudent.student_id == student.id).all()
        if not groups:
            await message.answer("Вы не состоите ни в одной группе.")
            return
        schedules = []
        for group in groups:
            schedule = session.query(Schedule).filter_by(group_id=group.id).first()
            schedules.append(f"Группа '{group.name}': {schedule.content if schedule else 'Расписание не задано'}")
        schedules_text = "\n\n".join(schedules)
        await message.answer(f"Ваши группы и расписания:\n\n{schedules_text}")
    finally:
        session.close()


# Updated handler to select and send training program file
@router.message(F.text == "Программа тренировок")
async def handle_training_program(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
        # Query groups through GroupStudent junction table
        groups = session.query(Group).join(GroupStudent).filter(GroupStudent.student_id == student.id).all()
        if not groups:
            await message.answer("Вы не состоите ни в одной группе.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=g.name, callback_data=f"select_program_{g.id}")]
            for g in groups
        ])
        await message.answer("Выберите группу, чтобы получить программу тренировок:", reply_markup=keyboard)
        await state.set_state(ProgramSelection.waiting_for_group)
    finally:
        session.close()


# Handler for group selection to send program file
@router.callback_query(F.data.startswith("select_program_"))
async def handle_program_selection(callback: types.CallbackQuery, state: FSMContext):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        if not group.program_file:
            await callback.answer("Для этой группы не загружена программа тренировок.")
            return
        await callback.message.delete()  # Remove the group selection message
        await callback.message.answer_document(
            document=types.FSInputFile(path=group.program_file),
            caption=f"Программа тренировок для группы '{group.name}'"
        )
        await state.clear()
    finally:
        session.close()
    await callback.answer()


@router.message(F.text == "Питание")
async def handle_nutrition(message: types.Message):
    await message.answer("Вы выбрали: Питание. Расскажите больше, чтобы я помог составить рацион.")


@router.message(F.text == "Прогресс")
async def handle_progress(message: types.Message):
    await message.answer("Выберите действие:", reply_markup=get_progress_menu())


@router.callback_query(F.data == "upload_training")
async def handle_upload_training(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Пожалуйста, отправьте файл или текстовое сообщение с описанием вашей тренировки.")
    await state.set_state(ProgressStates.waiting_for_training_data)
    await callback.answer()


@router.callback_query(F.data == "upload_photo")
async def handle_upload_photo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Пожалуйста, отправьте фото.")
    await state.set_state(ProgressStates.waiting_for_photo)
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Возвращаемся в главное меню:", reply_markup=get_main_menu())
    await callback.answer()


@router.message(ProgressStates.waiting_for_training_data, F.document | F.text)
async def handle_training_data(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            await state.clear()
            return
        progress = Progress(student_id=student.id, type='training', date=datetime.datetime.now())
        if message.document:
            file_id = message.document.file_id
            file = await message.bot.get_file(file_id)
            file_name = f"{int(time.time())}_{message.document.file_name}"
            file_path = os.path.join("uploads", "progress", str(student.id), file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            await message.bot.download_file(file.file_path, file_path)
            progress.file_path = file_path
        elif message.text:
            progress.content = message.text
        session.add(progress)
        session.commit()
        await message.answer("Ваша тренировка сохранена.")
        await state.clear()
    finally:
        session.close()


@router.message(ProgressStates.waiting_for_photo, F.photo | F.document)
async def handle_photo(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            await state.clear()
            return
        progress = Progress(student_id=student.id, type='photo', date=datetime.datetime.now())
        if message.photo:
            file_id = message.photo[-1].file_id
            file = await message.bot.get_file(file_id)
            file_name = f"{int(time.time())}_photo.jpg"
            file_path = os.path.join("uploads", "progress", str(student.id), file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            await message.bot.download_file(file.file_path, file_path)
            progress.file_path = file_path
        elif message.document:
            if message.document.mime_type.startswith('image/'):
                file_id = message.document.file_id
                file = await message.bot.get_file(file_id)
                file_name = f"{int(time.time())}_{message.document.file_name}"
                file_path = os.path.join("uploads", "progress", str(student.id), file_name)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                await message.bot.download_file(file.file_path, file_path)
                progress.file_path = file_path
            else:
                await message.answer("Пожалуйста, отправьте изображение.")
                return
        session.add(progress)
        session.commit()
        await message.answer("Ваше фото сохранено.")
        await state.clear()
    finally:
        session.close()


@router.message(F.text == "База знаний")
async def handle_knowledge_base(message: types.Message):
    await message.answer("Вы выбрали: База знаний. Вот полезные материалы для вас...")
