from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from database import Base, Session
from models.models import Student, Trainer, Group, Schedule, GroupCreation

router = Router()

# Check if user is admin (trainer)
def is_admin(telegram_id):
    session = Session()
    try:
        trainer = session.query(Trainer).filter_by(telegram_id=str(telegram_id)).first()
        return trainer is not None
    finally:
        session.close()

# Admin menu for trainers
def get_admin_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Просмотреть профили учеников"), KeyboardButton(text="Просмотреть список групп")],
            [KeyboardButton(text="Создать группу"), KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

@router.message(F.text == "Создать группу")
async def create_group(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только тренерам.")
        return
    await message.answer("Введите название новой группы:")
    await state.set_state(GroupCreation.waiting_for_name)

# Обработчик ввода названия группы
@router.message(GroupCreation.waiting_for_name)
async def handle_group_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    group_name = message.text.strip()
    session = Session()
    try:
        trainer = session.query(Trainer).filter_by(telegram_id=str(message.from_user.id)).first()
        group = Group(name=group_name, trainer_id=trainer.id)
        session.add(group)
        session.commit()
        await state.update_data(group_id=group.id)  # Сохраняем ID группы
        # Показываем список учеников
        students = session.query(Student).all()
        if not students:
            await message.answer("Нет зарегистрированных учеников.")
            await state.clear()
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{s.name or 'N/A'} (@{s.username or 'N/A'})", callback_data=f"add_student_{s.telegram_id}")]
            for s in students
        ])
        await message.answer(f"Группа '{group_name}' создана. Выберите учеников для добавления:", reply_markup=keyboard)
        await state.set_state(GroupCreation.waiting_for_students)
    finally:
        session.close()

# Обработчик выбора учеников
@router.callback_query(F.data.startswith("add_student_"))
async def add_student_to_group(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Эта функция доступна только тренерам.")
        return
    telegram_id = callback.data.replace("add_student_", "")
    session = Session()
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        group = session.query(Group).filter_by(id=group_id).first()
        student = session.query(Student).filter_by(telegram_id=telegram_id).first()
        if student and group:
            if student not in group.students:
                group.students.append(student)
                session.commit()
                await callback.answer(f"Ученик {student.name or 'N/A'} добавлен в группу '{group.name}'.")
            else:
                await callback.answer(f"Ученик {student.name or 'N/A'} уже в группе.")
        else:
            await callback.answer("Ошибка: группа или ученик не найдены.")
    finally:
        session.close()
    # Обновляем список учеников
    students = session.query(Student).all()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{s.name or 'N/A'} (@{s.username or 'N/A'})", callback_data=f"add_student_{s.telegram_id}")]
        for s in students if s not in session.query(Group).filter_by(id=group_id).first().students
    ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="Завершить выбор", callback_data="finish_selection")])
    await callback.message.edit_reply_markup(reply_markup=keyboard)

# Обработчик завершения выбора
@router.callback_query(F.data == "finish_selection")
async def finish_selection(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("group_id")
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        await callback.message.edit_text(f"Группа '{group.name}' успешно сформирована с {len(group.students)} {'учеником' if len(group.students) == 1 else 'учениками'}.")
        await state.clear()
    finally:
        session.close()


@router.message(F.text == "Формировать расписание")
async def create_schedule(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только тренерам.")
        return
    session = Session()
    try:
        groups = session.query(Group).filter_by(trainer_id=session.query(Trainer).filter_by(telegram_id=str(message.from_user.id)).first().id).all()
        if not groups:
            await message.answer("У вас нет групп. Создайте группу сначала.")
            return
        group_names = "\n".join([f"{g.id}: {g.name}" for g in groups])
        await message.answer(f"Выберите группу (введите ID):\n{group_names}\nФормат расписания: ID группы, дата (ДД.ММ.ГГГГ), время (ЧЧ:ММ), описание")
    finally:
        session.close()

@router.message(lambda message: message.text.count(',') == 3)
async def handle_schedule(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        group_id, date, time, description = [x.strip() for x in message.text.split(',')]
        session = Session()
        try:
            schedule = Schedule(group_id=group_id, date=date, time=time, description=description)
            session.add(schedule)
            session.commit()
            await message.answer(f"Расписание создано: {date} {time} - {description}")
        finally:
            session.close()
    except ValueError:
        await message.answer("Неверный формат. Используйте: ID группы, дата (ДД.ММ.ГГГГ), время (ЧЧ:ММ), описание")

@router.message(F.text == "Просмотреть профили учеников")
async def view_student_profiles(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только тренерам.")
        return
    session = Session()
    try:
        students = session.query(Student).all()
        if not students:
            await message.answer("Нет зарегистрированных учеников.")
            return
        profiles = "\n".join([f"ID: {s.telegram_id}, Username: @{s.username or 'N/A'}, Name: {s.name or 'N/A'}" for s in students])
        await message.answer(f"Профили учеников:\n{profiles}")
    finally:
        session.close()

@router.message(F.text == "Просмотреть список групп")
async def view_groups(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта функция доступна только тренерам.")
        return
    session = Session()
    try:
        trainer = session.query(Trainer).filter_by(telegram_id=str(message.from_user.id)).first()
        if not trainer:
            await message.answer("Вы не зарегистрированы как тренер.")
            return
        groups = session.query(Group).filter_by(trainer_id=trainer.id).all()
        if not groups:
            await message.answer("У вас нет созданных групп.")
            return
        group_list = []
        for g in groups:
            # Получаем список учеников в группе
            students = g.students
            student_info = ", ".join([f"{s.name or 'N/A'} (@{s.username or 'N/A'})" for s in students]) if students else "Нет учеников"
            group_list.append(f"ID: {g.id}, Название: {g.name}\nУченики: {student_info}")
        await message.answer(f"Ваши группы:\n\n" + "\n\n".join(group_list))
    finally:
        session.close()

@router.message(F.text == "Вернуться в главное меню")
async def back_to_main_menu(message: types.Message):
    from handlers.start import get_main_menu
    await message.answer("Возвращаемся в главное меню:", reply_markup=get_admin_menu())