from filters import IsAdmin

@router.message(IsAdmin(), F.text == "База знаний")
async def handle_knowledge_base_admin(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить материалы", callback_data="add_knowledge")],
        [InlineKeyboardButton(text="Удалить материалы", callback_data="delete_knowledge")]
    ])
    await message.answer("Выберите действие:", reply_markup=keyboard)