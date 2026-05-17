from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_user_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Мои подписки", callback_data="my_keys")
    builder.button(text="💳 Оплатить", callback_data="pay_info")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_extend_kb(key_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Продлить на 1 мес", callback_data=f"extend_{key_id}_30")
    builder.button(text="Продлить на 3 мес", callback_data=f"extend_{key_id}_90")
    builder.button(text="Продлить на 1 год", callback_data=f"extend_{key_id}_365")
    builder.button(text="❌ Удалить ключ", callback_data=f"admin_delete_{key_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_unsubscribe_kb(key_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отказаться от подписки", callback_data=f"user_unsub_{key_id}"
    )
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_unsub_kb(key_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, уверен", callback_data=f"confirm_unsub_{key_id}")
    builder.button(text="🔙 Назад", callback_data="my_keys")
    builder.adjust(1)
    return builder.as_markup()
