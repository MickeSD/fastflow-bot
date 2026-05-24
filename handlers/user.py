import html
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dependency_injector.wiring import Provide, inject

from application.services.vpn import VpnService
from core.config import ADMIN_ID, PANELS, PAYMENT_PHONE
from core.di import Container
from infrastructure.repositories import KeyRecord, KeyRepository
from keyboards.inline import get_confirm_unsub_kb, get_user_main_kb

router = Router()


@router.message(CommandStart())
@inject
async def cmd_start(
    message: Message,
    key_repo: KeyRepository = Provide[Container.key_repo]
) -> None:
    if not message.from_user:
        return

    await key_repo.upsert_user(message.from_user.id, message.from_user.username or "no_username")

    await message.answer(
        "Привет! Здесь ты можешь управлять своим VPN.", reply_markup=get_user_main_kb()
    )

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("❌ Действие отменено.")

@router.callback_query(F.data == "my_keys")
@inject
async def show_keys(
    callback: CallbackQuery,
    key_repo: KeyRepository = Provide[Container.key_repo]
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    keys = await key_repo.get_user_keys(callback.from_user.id)

    if not keys:
        try:
            await callback.message.edit_text("У тебя нет активных ключей.", reply_markup=get_user_main_kb())
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    grouped_keys: dict[str, list[KeyRecord]] = {}
    for k in keys:
        host = k["panel_host"]
        if host not in grouped_keys:
            grouped_keys[host] = []
        grouped_keys[host].append(k)

    text = "🔑 <b>Твои подписки:</b>\n\n"
    local_id_counter = 1
    builder = InlineKeyboardBuilder()

    for host, keys_list in grouped_keys.items():
        panel_info = PANELS.get(host, {})
        server_title = panel_info.get("name", f"🌐 СЕРВЕР: {host}")
        text += f"<b>{server_title}</b>\n"

        for k in keys_list:
            key_id = k["id"]
            vless_key = k["vless_key"]
            price = k["price"]
            date = k["next_payment_date"]

            parsed = urlparse(vless_key)
            key_name = html.escape(parsed.fragment) if parsed.fragment else "Без названия"

            text += (
                f"  {local_id_counter}. 🏷 <b>{key_name}</b>\n"
                f"     📅 До: <code>{date}</code>\n"
                f"     💰 Цена: {price}₽\n"
                f"     🔗 <code>{vless_key}</code>\n\n"
            )

            builder.button(text=f"❌ Отказаться от №{local_id_counter} ({key_name[:10]})", callback_data=f"user_unsub_{key_id}")
            local_id_counter += 1

    text += "Чтобы отказаться от подписки, выбери номер ниже:"
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "back_main")
async def back_to_main_handler(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    try:
        await callback.message.edit_text(
            "Привет! Здесь ты можешь управлять своим VPN.",
            reply_markup=get_user_main_kb(),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("user_unsub_"))
@inject
async def user_unsub_confirm(
    callback: CallbackQuery,
    key_repo: KeyRepository = Provide[Container.key_repo] # ✅ Заменили старый get_key_info
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    key_id = int(callback.data.split("_")[2])
    key_info = await key_repo.get_key_info(key_id)

    if not key_info or key_info["tg_id"] != callback.from_user.id:
        await callback.answer("❌ Это не твой ключ!", show_alert=True)
        return

    await callback.message.edit_text(
        "⚠️ Ты уверен, что хочешь отказаться от подписки?\nКлюч будет немедленно удален из системы.",
        reply_markup=get_confirm_unsub_kb(key_id),
    )

@router.callback_query(F.data.startswith("confirm_unsub_"))
@inject
async def user_unsub_final(
    callback: CallbackQuery,
    bot: Bot,
    vpn_service: VpnService = Provide[Container.vpn_service] # ✅ Вызываем Сервис!
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    key_id = int(callback.data.split("_")[2])

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # ✅ БОЖЕСТВЕННАЯ ЧИСТОТА: Весь огромный старый код удаления превратился в одну строку!
    success, msg_text = await vpn_service.cancel_subscription(key_id, callback.from_user.id)

    if success:
        user_info = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"
        await bot.send_message(ADMIN_ID, f"🔔 Пользователь {user_info} ОТКАЗАЛСЯ от подписки.")

    await callback.message.edit_text(msg_text)
    await callback.answer()

@router.callback_query(F.data == "pay_info")
async def pay_info_handler(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    text = (
        "💳 <b>Реквизиты для оплаты:</b>\n\n"
        "Перевод по номеру телефона (СБП):\n"
        f"<code>{PAYMENT_PHONE}</code> (Сбербанк)\n\n"
        "После перевода, пожалуйста, отправьте скриншот чека @MickleD."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")

    try:
        await callback.message.edit_text(
            text, parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass
    await callback.answer()
