import html
import json
import os
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import structlog
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from dependency_injector.wiring import Provide, inject

from application.services.vpn import VpnService
from core.config import ADMIN_ID, PANELS
from core.di import Container
from infrastructure.repositories import KeyRepository
from keyboards.inline import get_admin_extend_kb

logger = structlog.get_logger(__name__)


class AdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id == ADMIN_ID


router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class AddKeyFSM(StatesGroup):
    tg_id = State()
    vless_key = State()
    inbound_id = State()
    price = State()
    payment_date = State()

@router.message(Command("add_key"))
async def cmd_add_key(message: Message, state: FSMContext) -> None:
    # ✅ Лог запуска генерации ключа админом
    logger.info("admin_command_add_key", admin_id=message.from_user.id if message.from_user else None)
    await message.answer("Введи Telegram ID или @username пользователя:")
    await state.set_state(AddKeyFSM.tg_id)


@router.message(StateFilter(AddKeyFSM.tg_id), F.text, ~F.text.startswith("/"))
@inject
async def process_tg_id(
    message: Message,
    state: FSMContext,
    key_repo: KeyRepository = Provide[Container.key_repo] # ✅ DI
) -> None:
    if not message.text or not message.from_user:
        return

    # Явно указываем тип переменной, чтобы mypy не пугался
    target_id: int | None = None

    if message.text.isdigit():
        target_id = int(message.text)
    else:
        target_id = await key_repo.get_id_by_username(message.text)

    if not target_id:
        await message.answer("❌ Пользователь не найден в БД. Убедись, что он нажимал /start, или введи числовой ID:")
        return

    await state.update_data(tg_id=target_id)
    await message.answer(f"✅ Пользователь найден (ID: {target_id}). Теперь отправь VLESS ключ:")
    await state.set_state(AddKeyFSM.vless_key)


@router.message(StateFilter(AddKeyFSM.vless_key), F.text, ~F.text.startswith("/"))
async def process_vless(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    msg_text = message.text

    parsed = urlparse(msg_text)
    if parsed.scheme not in ["vless", "hysteria2"] or not parsed.username or not parsed.hostname:
        await message.answer("❌ Это не похоже на правильный ключ (VLESS или Hysteria2). Попробуй еще раз:")
        return

    uuid = str(parsed.username)
    host = str(parsed.hostname)
    query = parse_qs(parsed.query)
    flow = query.get("flow", [""])[0]

    panel_host = host
    if panel_host not in PANELS:
        matched = next((str(k) for k, v in PANELS.items() if host in str(v.get('url', '')) or str(k) in msg_text), None)
        panel_host = matched if matched else (str(list(PANELS.keys())[0]) if PANELS else host)

    await state.update_data(vless_key=msg_text, uuid=uuid, panel_host=panel_host, flow=flow, scheme=parsed.scheme)
    await message.answer("Введи Inbound ID панели (номер подключения, например 1 или 3):")
    await state.set_state(AddKeyFSM.inbound_id)


@router.message(StateFilter(AddKeyFSM.inbound_id), F.text, ~F.text.startswith("/"))
async def process_inbound_id(message: Message, state: FSMContext) -> None:
    if not message.text or not message.from_user:
        return

    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Inbound ID должен быть положительным числом (больше нуля). Попробуй еще раз:")
        return

    inbound_id = int(message.text)
    data = await state.get_data()
    panel_host = data.get("panel_host")

    if panel_host:
        from services.panel import inbound_exists
        status_msg = await message.answer("🔍 Проверяю существование подключения на панели 3x-ui...")
        check_result = await inbound_exists(str(panel_host), inbound_id)

        try:
            await status_msg.delete()
        except Exception:
            pass

        if check_result is None:
            await message.answer(
                f"⚠️ Предупреждение: Сервер {panel_host} временно недоступен.\nНе удалось проверить наличие Inbound ID {inbound_id}, но конфигурация будет сохранена."
            )
        elif check_result is False:
            await message.answer(f"❌ Подключение с ID {inbound_id} не найдено на сервере {panel_host}.\nПроверь ID подключения в панели 3x-ui и попробуй ввести снова:")
            return

    await state.update_data(inbound_id=inbound_id)
    await message.answer("Введи цену в рублях (число):")
    await state.set_state(AddKeyFSM.price)


@router.message(StateFilter(AddKeyFSM.price), F.text, ~F.text.startswith("/"))
async def process_price(message: Message, state: FSMContext) -> None:
    if not message.text or not message.from_user:
        return

    if not message.text.isdigit() or int(message.text) < 0 or int(message.text) > 10000:
        await message.answer("❌ Цена должна быть в диапазоне от 0 до 10 000 рублей. Попробуй еще раз:")
        return

    await state.update_data(price=int(message.text))
    await message.answer("Введи дату следующей оплаты в формате YYYY-MM-DD (например, 2026-06-15):")
    await state.set_state(AddKeyFSM.payment_date)


@router.message(StateFilter(AddKeyFSM.payment_date), F.text, ~F.text.startswith("/"))
@inject
async def process_date(
    message: Message,
    state: FSMContext,
    key_repo: KeyRepository = Provide[Container.key_repo] # ✅ DI
) -> None:
    if not message.text or not message.from_user:
        return

    try:
        input_date = datetime.strptime(message.text, "%Y-%m-%d").date()
        current_date = datetime.now(ZoneInfo("Europe/Moscow")).date()

        if input_date < current_date:
            await message.answer("❌ Дата не может быть в прошлом! Введи правильную дату (YYYY-MM-DD):")
            return

        valid_date = input_date.strftime("%Y-%m-%d")
    except ValueError:
        await message.answer("❌ Неверный формат. Используй YYYY-MM-DD:")
        return

    data = await state.get_data()
    host = data.get("panel_host")
    inbound = data.get("inbound_id", 1)
    scheme = data.get("scheme", "vless")

    if not host or not data.get("uuid"):
        await message.answer("❌ Критическая ошибка: Не удалось извлечь UUID или IP сервера из ключа.")
        return

    # Запрашиваем имя через репозиторий
    real_name = await key_repo.get_username(data["tg_id"])
    if not real_name:
        try:
            if not message.bot:
                return
            chat_info = await message.bot.get_chat(data["tg_id"])
            real_name = chat_info.username or chat_info.first_name or "Client"
        except Exception:
            real_name = "Client"

    unique_email = f"user_{data['tg_id']}_{str(data.get('uuid'))[:5]}"

    if scheme == "hysteria2":
        client_settings = {"password": data.get("uuid"), "email": unique_email, "limitIp": 0, "totalGB": 0, "expiryTime": 0, "enable": True}
    else:
        client_settings = {"id": data.get("uuid"), "alterId": 0, "email": unique_email, "limitIp": 0, "totalGB": 0, "expiryTime": 0, "enable": True}
        if data.get("flow"):
            client_settings["flow"] = data.get("flow")

    settings_json = json.dumps(client_settings)

    try:
        await key_repo.add_key(
            tg_id=data["tg_id"], username=real_name, vless_key=data["vless_key"], price=data["price"],
            payment_date=valid_date, uuid=str(data.get('uuid')), panel_host=host, inbound_id=inbound, settings=settings_json,
        )
        # ✅ Аудит-лог: Ключ успешно создан админом
        logger.info(
            "admin_action_add_key_success",
            admin_id=message.from_user.id if message.from_user else None,
            target_tg_id=data["tg_id"],
            panel_host=host,
            price=data["price"]
        )
        await message.answer(f"✅ Ключ добавлен для @{real_name}! Сервер: `{host}`.")
    except Exception as e:
        logger.error(f"Сбой добавления ключа в БД: {e}")
        err_msg = str(e) if isinstance(e, ValueError) else "Произошла ошибка при сохранении в базу данных. Проверь логи."
        await message.answer(f"❌ Ошибка: {err_msg}")
    finally:
        await state.clear()


@router.callback_query(F.data.startswith("extend_"))
@inject
async def process_extend(
    callback: CallbackQuery,
    vpn_service: VpnService = Provide[Container.vpn_service]
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    parts = callback.data.split("_")
    key_id = int(parts[1])
    days = int(parts[2])

    if days > 366:
        await callback.answer("❌ Запрещено продлевать ключ более чем на 1 год за один раз!", show_alert=True)
        return

    success, status_msg = await vpn_service.extend_key(key_id, days)
    await callback.answer(status_msg, show_alert=True)


@router.message(Command("users"))
@inject
async def cmd_users_router(
    message: Message,
    key_repo: KeyRepository = Provide[Container.key_repo] # ✅ DI
) -> None:
    if not message.text or not message.from_user:
        return

    parts = message.text.split()

    if len(parts) == 1:
        users = await key_repo.get_users_grouped()
        if not users:
            await message.answer("База пуста.")
            return

        report = "👥 Список активных пользователей:\n\n"
        for u in users:
            safe_username = html.escape(str(u["username"]))
            report += f"ID: {u['tg_id']} | @{safe_username} | Ключей: {u['keys_count']} | Сумма: {u['total_price']}₽\n"

        if len(report) > 3500:
            import time

            from core.config import BASE_DIR
            file_path = BASE_DIR / f"users_report_{message.from_user.id}_{int(time.time())}.txt"
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(report)
                await message.answer_document(FSInputFile(str(file_path)), caption="👥 Список пользователей слишком длинный. Выгружен файлом.")
            except Exception as e:
                await message.answer(f"❌ Ошибка отправки файла: {e}")
            finally:
                if file_path.exists():
                    os.remove(file_path)
        else:
            await message.answer(f"<pre>{report}</pre>", parse_mode="HTML")

        await message.answer("Для просмотра ключей: <code>/users ID</code>\nУправление: <code>/key ID</code>", parse_mode="HTML")
        return

    query = parts[1]
    target_id = int(query) if query.isdigit() else await key_repo.get_id_by_username(query)

    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return

    user_keys = await key_repo.get_user_keys(target_id)
    if not user_keys:
        await message.answer(f"У пользователя {query} нет активных ключей.")
        return

    total_price = sum(k["price"] for k in user_keys)
    text = f"👤 <b>Профиль пользователя</b> <code>{target_id}</code>\n💰 Общая сумма к оплате: <b>{total_price}₽/мес</b>\n\n🔑 <b>Активные ключи:</b>\n"

    for k in user_keys:
        text += f"🔹 Ключ <code>{k['id']}</code> | Сервер: {k['panel_host']} | До {k['next_payment_date']} | {k['price']}₽\n"

    text += "\nУправлять ключом: <code>/key ID_ключа</code>"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("key"))
@inject
async def cmd_manage_key(
    message: Message,
    key_repo: KeyRepository = Provide[Container.key_repo]
) -> None:
    if not message.text or not message.from_user:
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/key ID_ключа</code>", parse_mode="HTML")
        return

    key_id = int(parts[1])
    key_info = await key_repo.get_key_info(key_id)

    if not key_info:
        await message.answer(f"❌ Ключ ID {key_id} не найден или уже деактивирован.")
        return

    # ✅ Лог доступа админа к конкретному ключу
    logger.info("admin_command_manage_key", admin_id=message.from_user.id if message.from_user else None, key_id=key_id)

    status = "✅ Активен" if key_info["is_active"] else "❌ Отключен"
    short_key = f"{key_info['vless_key'][:40]}..." if len(key_info["vless_key"]) > 40 else key_info["vless_key"]

    text = (
        f"🏷 <b>Управление ключом ID {key_id}</b>\n\n"
        f"👤 Владелец: <code>{key_info['tg_id']}</code>\n"
        f"🌐 Сервер: {key_info['panel_host']}\n"
        f"🔌 Inbound: {key_info['inbound_id']}\n"
        f"📊 Статус: {status}\n"
        f"📅 Истекает: <b>{key_info['next_payment_date']}</b>\n"
        f"💰 Цена: {key_info['price']}₽\n\n"
        f"🔑 <b>Ключ:</b>\n<code>{html.escape(short_key)}</code>\n" # ✅ Безопасное экранирование html.escape
    )

    await message.answer(text, reply_markup=get_admin_extend_kb(key_id), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_delete_"))
@inject
async def admin_delete_handler(
    callback: CallbackQuery,
    vpn_service: VpnService = Provide[Container.vpn_service], # ✅ Используем бизнес-сервис
    key_repo: KeyRepository = Provide[Container.key_repo]
) -> None:
    if not isinstance(callback.message, Message) or not callback.data:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    key_id = int(callback.data.split("_")[2])
    key_info = await key_repo.get_key_info(key_id)
    if not key_info:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    # ✅ Аудит-лог: Ключ принудительно удален админом
    logger.info(
        "admin_action_delete_key",
        admin_id=callback.from_user.id if callback.from_user else None,
        key_id=key_id,
        target_tg_id=key_info["tg_id"],
        panel_host=key_info["panel_host"]
    )
    success, msg_text = await vpn_service.cancel_subscription(key_id, key_info["tg_id"])

    if success:
        await callback.message.edit_text(f"✅ Ключ ID {key_id} успешно удален с сервера и деактивирован в базе.")
    else:
        await callback.message.edit_text(msg_text)

    await callback.answer()
