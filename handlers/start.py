import PyPDF2
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import datetime
from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import FSInputFile
from aiogram.filters import Command
from database import Session
from models import Student, GroupStudent, PaymentRequest, Trainer, Group, Schedule, Progress, KnowledgeBase
from handlers.admin import is_admin, get_admin_menu
import ai_model
import asyncio
from filters import IsAdmin
import os
import time
import zipfile
import tempfile
from dotenv import load_dotenv

router = Router()
load_dotenv()


class NutritionStates(StatesGroup):
    waiting_for_nutrition_data = State()


class AIReviewStates(StatesGroup):
    waiting_for_query = State()


class ProgramSelection(StatesGroup):
    waiting_for_group = State()


class PaymentStates(StatesGroup):
    waiting_for_screenshot = State()
    waiting_for_sessions = State()


class ProgressStates(StatesGroup):
    waiting_for_training_data = State()
    waiting_for_photo = State()


def truncate_text(text, word_limit=200):
    words = text.split()
    if len(words) > word_limit:
        return " ".join(words[:word_limit]) + "..."
    return text


def extract_text_from_file(file_path):
    try:
        if file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        elif file_path.endswith('.pdf'):
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text
        return ""
    except Exception:
        return ""


def get_main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Занятия с тренером"), KeyboardButton(text="График тренировок")],
            [KeyboardButton(text="Программа тренировок"), KeyboardButton(text="Питание")],
            [KeyboardButton(text="Прогресс"), KeyboardButton(text="База знаний")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard


def get_progress_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="загрузить тренировку", callback_data="upload_training")],
        [InlineKeyboardButton(text="загрузить фото", callback_data="upload_photo")],
        [InlineKeyboardButton(text="просмотреть историю тренировок", callback_data="view_training_history")],
        [InlineKeyboardButton(text="посмотреть историю фото", callback_data="view_photo_history")],
        [InlineKeyboardButton(text="ии-обзор истории тренировок", callback_data="ai_review")],
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
        await message.answer(
            f"У вас осталось {student.remaining_sessions} оплаченных занятий.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
            ])
        )
        pending_request = session.query(PaymentRequest).filter_by(student_id=student.id, status='pending').first()
        if pending_request:
            await message.answer(
                f"Ваш запрос на {pending_request.sessions_requested} занятий находится на рассмотрении.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
                ])
            )
        else:
            await message.answer(
                "Отправьте файл (например, скриншот или документ) с подтверждением оплаты.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
                ])
            )
            await state.set_state(PaymentStates.waiting_for_screenshot)
    finally:
        session.close()


# Added cancel button to return to main menu
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
    await message.answer(
        "Файл получен. Укажите количество занятий, за которые вы оплатили.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
        ])
    )
    await state.set_state(PaymentStates.waiting_for_sessions)


# Added cancel button to return to main menu
@router.message(F.text, PaymentStates.waiting_for_sessions)
async def handle_sessions(message: types.Message, state: FSMContext):
    try:
        sessions = int(message.text)
        if sessions <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "Пожалуйста, введите положительное целое число.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
            ])
        )
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
        await message.answer("Ваш запрос отправлен тренеру на рассмотрение.", reply_markup=get_main_menu())
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


@router.message(F.text == "График тренировок")
async def handle_training_schedule(message: types.Message):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
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


@router.message(F.text == "Программа тренировок")
async def handle_training_program(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
        groups = session.query(Group).join(GroupStudent).filter(GroupStudent.student_id == student.id).all()
        if not groups:
            await message.answer("Вы не состоите ни в одной группе.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                                            [InlineKeyboardButton(text=g.name,
                                                                                  callback_data=f"select_program_{g.id}")]
                                                            for g in groups
                                                        ] + [[InlineKeyboardButton(text="Отмена",
                                                                                   callback_data="back_to_main")]])
        await message.answer("Выберите группу, чтобы получить программу тренировок:", reply_markup=keyboard)
        await state.set_state(ProgramSelection.waiting_for_group)
    finally:
        session.close()


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
        await callback.message.delete()
        await callback.message.answer_document(
            document=types.FSInputFile(path=group.program_file),
            caption=f"Программа тренировок для группы '{group.name}'"
        )
        await state.clear()
    finally:
        session.close()
    await callback.answer()


@router.message(F.text == "Питание")
async def handle_nutrition(message: types.Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, отправьте текст, фото или файл с информацией о вашем питании.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
        ])
    )
    await state.set_state(NutritionStates.waiting_for_nutrition_data)


@router.message(NutritionStates.waiting_for_nutrition_data, F.text | F.photo | F.document)
async def handle_nutrition_data(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            await state.clear()
            return
        progress = Progress(student_id=student.id, type='nutrition', date=datetime.datetime.now())
        if message.text:
            progress.content = message.text
        elif message.photo:
            file_id = message.photo[-1].file_id
            file = await message.bot.get_file(file_id)
            file_name = f"{int(time.time())}_nutrition_photo.jpg"
            file_path = os.path.join("uploads", "nutrition", str(student.id), file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            await message.bot.download_file(file.file_path, file_path)
            progress.file_path = file_path
        elif message.document:
            file_id = message.document.file_id
            file = await message.bot.get_file(file_id)
            file_name = f"{int(time.time())}_{message.document.file_name}"
            file_path = os.path.join("uploads", "nutrition", str(student.id), file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            await message.bot.download_file(file.file_path, file_path)
            progress.file_path = file_path
        session.add(progress)
        session.commit()
        await message.answer("Информация о питании сохранена.", reply_markup=get_main_menu())
        await state.clear()
    finally:
        session.close()


@router.message(F.text == "Прогресс")
async def handle_progress(message: types.Message):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            return
        await message.answer("Выберите действие:", reply_markup=get_progress_menu())
    finally:
        session.close()


@router.callback_query(F.data == "upload_training")
async def handle_upload_training(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Пожалуйста, отправьте файл или текстовое сообщение с описанием вашей тренировки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_progress")]
        ])
    )
    await state.set_state(ProgressStates.waiting_for_training_data)
    await callback.answer()


@router.callback_query(F.data == "upload_photo")
async def handle_upload_photo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Пожалуйста, отправьте фото.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_progress")]
        ])
    )
    await state.set_state(ProgressStates.waiting_for_photo)
    await callback.answer()

@router.callback_query(F.data == "back_to_progress")
async def handle_back_to_progress(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("Выберите действие:", reply_markup=get_progress_menu())
    await state.clear()
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


@router.callback_query(F.data == "view_training_history")
async def handle_view_training_history(callback: types.CallbackQuery):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(callback.from_user.id)).first()
        if not student:
            await callback.answer("Вы не зарегистрированы.", show_alert=True)
            return
        entries = (
            session.query(Progress)
            .filter_by(student_id=student.id, type='training')
            .order_by(Progress.date.desc())
            .limit(20)
            .all()
        )
        if not entries:
            await callback.message.edit_text("У вас нет записей о тренировках.")
            return
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = tmp.name
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            index_content = ""
            for entry in entries:
                if entry.content:
                    fname = f"training_{entry.id}.txt"
                    zipf.writestr(fname, entry.content)
                elif entry.file_path:
                    base = os.path.basename(entry.file_path)
                    fname = f"training_{entry.id}_{base}"
                    zipf.write(entry.file_path, fname)
                index_content += (
                    f"Entry ID: {entry.id}\n"
                    f"Date: {entry.date}\n"
                    f"File: {fname}\n\n"
                )
            zipf.writestr("index.txt", index_content)
        await callback.message.delete()
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(zip_path, filename="training_history.zip"),
            caption="Ваша история тренировок"
        )
        os.remove(zip_path)
    finally:
        session.close()
    await callback.answer()


@router.callback_query(F.data == "view_photo_history")
async def handle_view_photo_history(callback: types.CallbackQuery):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(callback.from_user.id)).first()
        if not student:
            await callback.answer("Вы не зарегистрированы.", show_alert=True)
            return
        entries = (
            session.query(Progress)
            .filter_by(student_id=student.id, type='photo')
            .order_by(Progress.date.desc())
            .limit(20)
            .all()
        )
        if not entries:
            await callback.message.edit_text("У вас нет загруженных фото.")
            return
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = tmp.name
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            index_content = ""
            for entry in entries:
                if entry.file_path:
                    base = os.path.basename(entry.file_path)
                    fname = f"photo_{entry.id}_{base}"
                    zipf.write(entry.file_path, fname)
                    index_content += (
                        f"Entry ID: {entry.id}\n"
                        f"Date: {entry.date}\n"
                        f"File: {fname}\n\n"
                    )
            zipf.writestr("index.txt", index_content)
        await callback.message.delete()
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(zip_path, filename="photo_history.zip"),
            caption="Ваша история фото"
        )
        os.remove(zip_path)
    finally:
        session.close()
    await callback.answer()


@router.callback_query(F.data == "ai_review")
async def handle_ai_review(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="back_to_progress")]
    ])
    await callback.message.edit_text(
        "Пожалуйста, опишите ваш запрос для анализа прогресса (например, что вы хотите узнать или улучшить):",
        reply_markup=keyboard
    )
    await state.set_state(AIReviewStates.waiting_for_query)
    await callback.answer()


@router.callback_query(F.data == "exit_ai_dialogue")
async def handle_exit_ai_dialogue(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("Вы вышли из диалога с ИИ.", reply_markup=get_main_menu())
    await state.clear()
    await callback.answer()


# Corrected indentation and completed AI call with proper error handling
@router.message(AIReviewStates.waiting_for_query, F.text)
async def handle_ai_review_query(message: types.Message, state: FSMContext):
    session = Session()
    try:
        student = session.query(Student).filter_by(telegram_id=str(message.from_user.id)).first()
        if not student:
            await message.answer("Вы не зарегистрированы. Используйте /start для регистрации.")
            await state.clear()
            return

        training_entries = session.query(Progress).filter_by(student_id=student.id, type='training').order_by(
            Progress.date.desc()).limit(5).all()
        nutrition_entries = session.query(Progress).filter_by(student_id=student.id, type='nutrition').order_by(
            Progress.date.desc()).limit(5).all()

        training_history = "\n".join([
            f"Training {i + 1} ({entry.date}): {truncate_text(entry.content or extract_text_from_file(entry.file_path))}"
            for i, entry in enumerate(training_entries)
        ]) if training_entries else "No recent training data available."
        nutrition_history = "\n".join([
            f"Nutrition {i + 1} ({entry.date}): {truncate_text(entry.content or extract_text_from_file(entry.file_path))}"
            for i, entry in enumerate(nutrition_entries)
        ]) if nutrition_entries else "No recent nutrition data available."

        knowledge_base_summary = ai_model.get_knowledge_base_summary(word_limit=16380)
        prompt = f"""
        Ты - фитнесс-тренер по пауэрлифтингу для подростков, твоя задача - проанализировать базу знаний, историю тренировок и питания ученика и ответить на его вопрос:
        {knowledge_base_summary}
        История тренировок:
        {training_history}
        История питания:
        {nutrition_history}

        Запрос от пользователя: {message.text}
        """

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, ai_model.generate_response, prompt)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад в главное меню", callback_data="back_to_main")]
        ])
        await message.answer(response, reply_markup=keyboard)
        await state.clear()

    except Exception as e:
        await message.answer(
            f"Произошла ошибка при обработке запроса: {str(e)}. Пожалуйста, попробуйте снова позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="back_to_progress")]
            ])
        )
        await state.clear()
    finally:
        session.close()


@router.message(~IsAdmin(), F.text == "База знаний")
async def handle_knowledge_base(message: types.Message):
    session = Session()
    try:
        materials = session.query(KnowledgeBase).all()
        if not materials:
            await message.answer("База знаний пуста.")
            return
        for material in materials:
            if material.type == 'text':
                await message.answer(material.content)
            elif material.type == 'file':
                await message.answer_document(FSInputFile(material.file_path))
            elif material.type == 'image':
                await message.answer_photo(FSInputFile(material.file_path))
    finally:
        session.close()
