import os
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
        await state.update_data(group_id=group.id)
        await message.answer(f"Группа '{group_name}' создана. Введите расписание в свободной форме:")
        await state.set_state(GroupCreation.waiting_for_schedule)
    finally:
        session.close()

@router.message(GroupCreation.waiting_for_schedule)
async def handle_group_schedule(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    schedule_content = message.text.strip()
    if not schedule_content:
        await message.answer("Расписание не может быть пустым. Пожалуйста, введите расписание:")
        return
    session = Session()
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        schedule = Schedule(group_id=group_id, content=schedule_content)
        session.add(schedule)
        session.commit()
        await message.answer("Расписание сохранено. Теперь загрузите файл с программой тренировок (например, PDF или документ):")
        await state.set_state(GroupCreation.waiting_for_program_file)
    finally:
        session.close()

@router.message(GroupCreation.waiting_for_program_file, F.document)
async def handle_program_file(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    document = message.document
    session = Session()
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await message.answer("Ошибка: группа не найдена.")
            await state.clear()
            return

        # Ensure uploads directory exists
        upload_dir = "uploads"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        # Generate unique file path
        file_extension = document.file_name.split('.')[-1] if '.' in document.file_name else 'file'
        file_path = os.path.join(upload_dir, f"group_{group_id}_program.{file_extension}")

        # Download and save the file
        file = await message.bot.get_file(document.file_id)
        await message.bot.download_file(file.file_path, file_path)

        # Save file path to group
        group.program_file = file_path
        session.commit()

        # Proceed to student selection
        students = session.query(Student).all()
        if not students:
            await message.answer("Нет зарегистрированных учеников.")
            await state.clear()
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{s.name or 'N/A'} (@{s.username or 'N/A'})", callback_data=f"add_student_{s.telegram_id}")]
            for s in students
        ])
        await message.answer("Файл программы тренировок сохранен. Выберите учеников для добавления:", reply_markup=keyboard)
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
        await message.answer(f"Выберите группу (введите ID):\n{group_names}\nФормат: ID группы, расписание (в свободной форме)")
    finally:
        session.close()


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
        buttons = [
            [InlineKeyboardButton(text=g.name, callback_data=f"edit_group_{g.id}")]
            for g in groups
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите группу:", reply_markup=inline_keyboard)
    finally:
        session.close()

@router.callback_query(F.data.startswith("edit_group_"))
async def handle_edit_group(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if group.trainer_id != trainer.id:
            await callback.answer("У вас нет доступа к этой группе.")
            return
        student_usernames = "\n".join([f"@{s.username or 'N/A'}" for s in group.students])
        buttons = [
            [InlineKeyboardButton(text="Изменить расписание", callback_data=f"change_schedule_{group_id}")],
            [InlineKeyboardButton(text="Добавить учеников", callback_data=f"add_students_{group_id}")],
            [InlineKeyboardButton(text="Удалить учеников", callback_data=f"remove_students_{group_id}")],
            [InlineKeyboardButton(text="Удалить группу", callback_data=f"delete_group_{group_id}")],
            [InlineKeyboardButton(text="Назад к списку групп", callback_data="back_to_groups")]
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Редактирование группы '{group.name}':\nУченики:\n{student_usernames}", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data == "back_to_groups")
async def handle_back_to_groups(callback: types.CallbackQuery):
    session = Session()
    try:
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if not trainer:
            await callback.message.edit_text("Вы не зарегистрированы как тренер.")
            return
        groups = session.query(Group).filter_by(trainer_id=trainer.id).all()
        if not groups:
            await callback.message.edit_text("У вас нет созданных групп.")
            return
        buttons = [
            [InlineKeyboardButton(text=g.name, callback_data=f"edit_group_{g.id}")]
            for g in groups
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите группу для редактирования:", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("delete_group_"))
async def handle_delete_group(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if group.trainer_id != trainer.id:
            await callback.answer("У вас нет доступа к этой группе.")
            return
        buttons = [
            [InlineKeyboardButton(text="Да", callback_data=f"confirm_delete_{group_id}"),
             InlineKeyboardButton(text="Нет", callback_data=f"edit_group_{group_id}")]
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Вы уверены, что хотите удалить группу '{group.name}'?", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_"))
async def handle_confirm_delete(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if group.trainer_id != trainer.id:
            await callback.answer("У вас нет доступа к этой группе.")
            return
        session.delete(group)
        session.commit()
        buttons = [
            [InlineKeyboardButton(text="Назад к списку групп", callback_data="back_to_groups")]
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Группа '{group.name}' удалена.", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("add_students_"))
async def handle_add_students(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if group.trainer_id != trainer.id:
            await callback.answer("У вас нет доступа к этой группе.")
            return
        students_not_in_group = session.query(Student).filter(~Student.groups.any(Group.id == group_id)).all()
        if not students_not_in_group:
            buttons = [
                [InlineKeyboardButton(text="Назад", callback_data=f"edit_group_{group_id}")]
            ]
            inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Нет учеников для добавления.", reply_markup=inline_keyboard)
            return
        buttons = [
            [InlineKeyboardButton(text=f"{s.name or 'N/A'} (@{s.username or 'N/A'})", callback_data=f"add_student_to_group_{group_id}_{s.telegram_id}")]
            for s in students_not_in_group
        ]
        buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"edit_group_{group_id}")])
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите ученика для добавления в группу:", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("add_student_to_group_"))
async def handle_add_student_to_group(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    group_id = parts[4]
    student_telegram_id = parts[5]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        student = session.query(Student).filter_by(telegram_id=student_telegram_id).first()
        if not group or not student:
            await callback.answer("Группа или ученик не найдены.")
            return
        if student in group.students:
            await callback.answer("Ученик уже в группе.")
            return
        group.students.append(student)
        session.commit()
        await callback.message.edit_text(
            f"Ученик {student.name or 'N/A'} добавлен в группу.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад к редактированию группы", callback_data=f"edit_group_{group_id}")]
            ])
        )
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("remove_students_"))
async def handle_remove_students(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        trainer = session.query(Trainer).filter_by(telegram_id=str(callback.from_user.id)).first()
        if group.trainer_id != trainer.id:
            await callback.answer("У вас нет доступа к этой группе.")
            return
        students_in_group = group.students
        if not students_in_group:
            buttons = [
                [InlineKeyboardButton(text="Назад", callback_data=f"edit_group_{group_id}")]
            ]
            inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("В группе нет учеников.", reply_markup=inline_keyboard)
            return
        buttons = [
            [InlineKeyboardButton(text=f"{s.name or 'N/A'} (@{s.username or 'N/A'})", callback_data=f"remove_student_from_group_{group_id}_{s.telegram_id}")]
            for s in students_in_group
        ]
        buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"edit_group_{group_id}")])
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите ученика для удаления из группы:", reply_markup=inline_keyboard)
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("remove_student_from_group_"))
async def handle_remove_student_from_group(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    group_id = parts[4]
    student_telegram_id = parts[5]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        student = session.query(Student).filter_by(telegram_id=student_telegram_id).first()
        if not group or not student:
            await callback.answer("Группа или ученик не найдены.")
            return
        if student not in group.students:
            await callback.answer("Ученик не в группе.")
            return
        group.students.remove(student)
        session.commit()
        await callback.message.edit_text(
            f"Ученик {student.name or 'N/A'} удален из группы.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад к редактированию группы", callback_data=f"edit_group_{group_id}")]
            ])
        )
    finally:
        session.close()
    await callback.answer()

@router.callback_query(F.data.startswith("change_schedule_"))
async def handle_change_schedule(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[-1]
    session = Session()
    try:
        group = session.query(Group).filter_by(id=group_id).first()
        if not group:
            await callback.answer("Группа не найдена.")
            return
        await callback.message.edit_text(
            f"Напишите расписание для группы '{group.name}' в свободной форме - его обработает ИИ"
        )
    finally:
        session.close()
    await callback.answer()

@router.message(F.text == "Вернуться в главное меню")
async def back_to_main_menu(message: types.Message):
    await message.answer("Возвращаемся в главное меню:", reply_markup=get_admin_menu())