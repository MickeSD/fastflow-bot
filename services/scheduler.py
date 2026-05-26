import asyncio
import glob
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite
import structlog
from aiogram import Bot

from application.services.vpn import VpnService
from core.config import ADMIN_ID, BASE_DIR
from core.utils.telegram import safe_send_message
from infrastructure.database import Database
from infrastructure.repositories import KeyRepository

logger = structlog.get_logger(__name__)

async def check_payments(ctx: dict) -> None:
    bot: Bot = ctx["bot"]
    key_repo: KeyRepository = ctx["container"].key_repo()
    vpn_service: VpnService = ctx["container"].vpn_service()

    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    keys = await key_repo.get_active_payment_rows()

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
        elif days_left < 0 and days_left > -7:
            # Грейс-период: просто спамим должника каждый день, но не удаляем
            await safe_send_message(bot, tg_id, f"🚨 Твой доступ (ID: {key_id}) ПРОСРОЧЕН на {abs(days_left)} дн.! Оплати {price}₽, иначе ключ скоро будет удален безвозвратно.")

        elif days_left <= -7:
            # Юзер не платил неделю после просрочки — удаляем с концами (Hard Delete)
            current_info = await key_repo.get_key_info(key_id)
            if not current_info or not current_info["is_active"]:
                continue

            success, msg_text = await vpn_service.cancel_subscription(key_id, tg_id)
            if success:
                await safe_send_message(bot, tg_id, f"💀 Твой VPN (ID: {key_id}) был полностью удален с сервера за длительную неуплату.")
                await safe_send_message(bot, ADMIN_ID, f"💀 Ключ {key_id} (Юзер {tg_id}) удален (долг > 7 дней).")
            else:
                await safe_send_message(bot, ADMIN_ID, f"⚠️ СБОЙ СЕТИ: Не удалось удалить ключ должника {key_id}.")

        await asyncio.sleep(0.1)

async def backup_database(ctx: dict) -> None:
    db: Database = ctx["container"].db()

    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    date_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y%m%d_%H%M")
    db_path = BASE_DIR / "db_data" / "vpn_database.db"
    backup_path = backup_dir / f"vpn_database_{date_str}.db"

    if not db_path.exists():
        logger.error("Файл БД не найден для бэкапа!")
        return

    try:
        async with aiosqlite.connect(backup_path) as backup_db:
            await db.backup(backup_db)

        # 🛑 Отправка сырой БД и логов в Telegram удалена ради безопасности!
        # Бэкапы надежно уходят в GDrive через наш зашифрованный bash-скрипт.
        logger.info("Локальный бэкап успешно сформирован.")
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}")
    finally:
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
