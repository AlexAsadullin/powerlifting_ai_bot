from aiogram.filters import BaseFilter
from handlers.admin import is_admin
from aiogram import types

class IsAdmin(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return is_admin(message.from_user.id)