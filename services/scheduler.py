import asyncio
import glob
import os
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile

from application.services.vpn import VpnService
from core.config import ADMIN_ID, BASE_DIR
from core.di import Container
from infrastructure.database import Database
from infrastructure.repositories import KeyRepository

logger = structlog.get_logger(__name__)


async def safe_send_message(bot: Bot, chat_id: int, text: str, max_retries: int = 3) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            await bot.send_message(chat_id, text)
            return True
        except TelegramRetryAfter as e:
            logger.warning(f"⏳ Telegram API лимит! Ждем {e.retry_after} сек. Попытка {attempt}/{max_retries}...")
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            logger.warning(f"🚫 Бот заблокирован пользователем {chat_id}.")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Ошибка отправки {attempt}/{max_retries} в чат {chat_id}: {e}")
            if attempt == max_retries:
                return False
            await asyncio.sleep(1)
    return False

async def safe_send_document(bot: Bot, chat_id: int, document: FSInputFile, caption: str = "") -> None:
    try:
        await bot.send_document(chat_id, document=document, caption=caption)
    except TelegramRetryAfter as e:
        logger.warning(f"⏳ Telegram API лимит (файлы)! Ждем {e.retry_after} сек...")
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_document(chat_id, document=document, caption=caption)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Не удалось отправить документ в {chat_id}: {e}")


async def check_payments(ctx: dict) -> None:
    # ✅ Достаем зависимости из контекста воркера
    bot: Bot = ctx["bot"]
    key_repo: KeyRepository = ctx["container"].key_repo()
    vpn_service: VpnService = ctx["container"].vpn_service()

    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    keys = await key_repo.get_all_active_keys()

    for key in keys:
        key_id = key["id"]
        tg_id = key["tg_id"]
        price = key["price"]
        payment_date_str = key["next_payment_date"]

        try:
            payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
            days_left = (payment_date - today).days
        except Exception as e:
            logger.error(f"Ошибка даты у ключа {key_id}: {e}")
            continue

        if days_left == 7:
            await safe_send_message(bot, tg_id, f"ℹ️ Твой VPN (ID: {key_id}) истекает через неделю. Цена: {price}₽.")
        elif days_left == 3:
            await safe_send_message(bot, tg_id, f"⚠️ Твой VPN (ID: {key_id}) истекает через 3 дня! Оплати {price}₽, чтобы не потерять доступ.")
        elif days_left == 1:
            await safe_send_message(bot, tg_id, f"‼️ Твой VPN (ID: {key_id}) истекает завтра! Стоимость продления: {price}₽.")
        elif days_left == 0:
            await safe_send_message(bot, tg_id, f"🚨 Твой VPN (ID: {key_id}) истекает СЕГОДНЯ! Оплати {price}₽, иначе завтра он будет отключен.")
        elif days_left < 0:
            # ✅ БОЖЕСТВЕННО! Вся логика удаления и парсинга делегирована сервису
            success, msg_text = await vpn_service.cancel_subscription(key_id, tg_id)

            if success:
                await safe_send_message(bot, tg_id, f"🚨 Твой доступ (ID: {key_id}) отключен за неуплату! Оплати {price}₽ для активации.")
                await safe_send_message(bot, ADMIN_ID, f"💀 Ключ {key_id} (Юзер {tg_id}) отключен и деактивирован.")
            else:
                await safe_send_message(bot, ADMIN_ID, f"⚠️ СБОЙ СЕТИ: Не удалось удалить ключ {key_id}. Ошибка: {msg_text}")

        await asyncio.sleep(0.1)

async def backup_database(ctx: dict) -> None:
    bot: Bot = ctx["bot"]
    db: Database = ctx["container"].db()

    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    date_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y%m%d_%H%M")
    db_path = BASE_DIR / "vpn_database.db"
    backup_path = backup_dir / f"vpn_database_{date_str}.db"
    log_path = BASE_DIR / "bot.log"
    temp_log = backup_dir / f"bot_{date_str}.log"

    if not db_path.exists():
        logger.error("Файл БД не найден для бэкапа!")
        return

    try:
        async with aiosqlite.connect(backup_path) as backup_db:
            await db.backup(backup_db) # ✅ Магия изолированной инфраструктуры

        await safe_send_document(bot, ADMIN_ID, FSInputFile(str(backup_path)), "📦 Нативный бэкап БД")

        if log_path.exists():
            shutil.copy2(log_path, temp_log)
            await safe_send_document(bot, ADMIN_ID, FSInputFile(str(temp_log)), "📝 Логи")

        logger.info("Бэкап успешно сформирован, сохранен локально и отправлен.")
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}")
    finally:
        if temp_log.exists():
            os.remove(temp_log)

        existing_backups = sorted(glob.glob(str(backup_dir / "vpn_database_*.db")))
        if len(existing_backups) > 7:
            for old_backup in existing_backups[:-7]:
                try:
                    os.remove(old_backup)
                except Exception:
                    pass

async def cleanup_inactive_keys(ctx: dict) -> None:
    key_repo: KeyRepository = ctx["container"].key_repo()

    try:
        deleted_count = await key_repo.delete_old_inactive_keys(90)
        if deleted_count > 0:
            logger.info(f"🧹 База очищена: удалено {deleted_count} старых неактивных ключей.")
    except Exception as e:
        logger.error(f"Ошибка при очистке старых ключей: {e}")
