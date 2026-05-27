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

    today_date = datetime.now(ZoneInfo("Europe/Moscow")).date()
    today_str = today_date.strftime("%Y-%m-%d")

    keys = await key_repo.get_active_payment_rows()

    for key in keys:
        key_id = key["id"]
        tg_id = key["tg_id"]
        price = key["price"]
        payment_date_str = key["next_payment_date"]
        last_notif = key.get("last_notification_sent")
        is_suspended = bool(key.get("is_suspended", 0))

        # ✅ ИДЕМПОТЕНТНОСТЬ: Если мы уже уведомляли этого юзера сегодня — пропускаем
        if last_notif == today_str:
            continue

        try:
            payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
            days_left = (payment_date - today_date).days
        except Exception as e:
            logger.error(f"Ошибка даты у ключа {key_id}: {e}")
            continue

        notified = False

        if days_left == 7:
            notified = await safe_send_message(bot, tg_id, f"ℹ️ Твой VPN (ID: {key_id}) истекает через неделю. Цена: {price}₽.")
        elif days_left == 3:
            notified = await safe_send_message(bot, tg_id, f"⚠️ Твой VPN (ID: {key_id}) истекает через 3 дня! Оплати {price}₽, чтобы не потерять доступ.")
        elif days_left == 1:
            notified = await safe_send_message(bot, tg_id, f"‼️ Твой VPN (ID: {key_id}) истекает завтра! Стоимость продления: {price}₽.")
        elif days_left == 0:
            notified = await safe_send_message(bot, tg_id, f"🚨 Твой VPN (ID: {key_id}) истекает СЕГОДНЯ! Оплати {price}₽, иначе завтра он будет приостановлен.")

        # ✅ GRACE PERIOD (от 1 до 6 дней просрочки)
        elif -7 < days_left < 0:
            if not is_suspended:
                # Приостанавливаем ключ на 3x-ui (трафик перестает идти)
                suspend_ok = await vpn_service.suspend_subscription(key_id)
                if suspend_ok:
                    logger.info(f"Ключ {key_id} приостановлен (Grace Period).")

            notified = await safe_send_message(bot, tg_id, f"🛑 Твой VPN (ID: {key_id}) ПРИОСТАНОВЛЕН за неуплату (просрочка {abs(days_left)} дн.).\nОплати {price}₽, чтобы мгновенно восстановить доступ, иначе через {7 - abs(days_left)} дн. он будет удален безвозвратно.")

        # ✅ HARD DELETE (Неуплата более 7 дней)
        elif days_left <= -7:
            success, msg_text = await vpn_service.cancel_subscription(key_id, tg_id)
            if success:
                await safe_send_message(bot, tg_id, f"💀 Твой VPN (ID: {key_id}) был полностью удален с сервера за длительную неуплату.")
                await safe_send_message(bot, ADMIN_ID, f"💀 Ключ {key_id} (Юзер {tg_id}) удален (долг > 7 дней).")
                notified = True
            else:
                await safe_send_message(bot, ADMIN_ID, f"⚠️ СБОЙ СЕТИ: Не удалось удалить ключ должника {key_id}.")

        # Запоминаем факт успешного уведомления, чтобы не тревожить юзера до завтра
        if notified:
            await key_repo.mark_notification_sent(key_id, today_str)

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
