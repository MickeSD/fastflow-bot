from datetime import datetime, timedelta
from typing import Any, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import aiosqlite
import structlog

from core.security import decrypt_data, encrypt_data, get_uuid_hash
from infrastructure.database import Database

logger = structlog.get_logger(__name__)

class KeyRecord(TypedDict):
    id: int
    tg_id: int
    vless_key: str
    price: int
    next_payment_date: str
    panel_host: str
    inbound_id: int
    is_active: bool
    settings: str | None
    deactivated_at: str | None

class KeyRepository:
    """Единая точка входа для любых операций с таблицами users и keys"""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_key_info(self, key_id: int) -> dict[str, Any] | None:
        async with self.db.connect() as conn:
            async with await conn.execute("SELECT * FROM keys WHERE id = ?", (key_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    row_dict = dict(row)
                    row_dict["vless_key"] = decrypt_data(row_dict["vless_key"])
                    row_dict["uuid"] = decrypt_data(row_dict["uuid"])
                    row_dict["settings"] = decrypt_data(row_dict["settings"]) if row_dict["settings"] else None
                    return row_dict
                return None

    async def get_user_keys(self, tg_id: int) -> list[KeyRecord]:
        async with self.db.connect() as conn:
            async with await conn.execute("SELECT * FROM keys WHERE tg_id = ? AND is_active = 1", (tg_id,)) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": r["id"],
                        "tg_id": r["tg_id"],
                        "vless_key": decrypt_data(r["vless_key"]),
                        "price": r["price"],
                        "next_payment_date": r["next_payment_date"],
                        "panel_host": r["panel_host"],
                        "inbound_id": r["inbound_id"],
                        "is_active": bool(r["is_active"]),
                        "settings": decrypt_data(r["settings"]) if r["settings"] else None,
                        "deactivated_at": r["deactivated_at"],
                    }
                    for r in rows
                ]

    async def deactivate_key(self, key_id: int) -> None:
        async with self.db.connect() as conn:
            now_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
            try:
                await conn.execute(
                    "UPDATE keys SET is_active = 0, deactivated_at = ? WHERE id = ?",
                    (now_str, key_id),
                )
                await conn.commit()
            except Exception as e:
                await conn.rollback() # Откат при любой ошибке
                logger.error("db_transaction_failed", error=str(e))
                raise e

    async def extend_subscription(self, key_id: int, days: int, new_settings: str) -> None: # Добавили new_settings
        async with self.db.connect() as conn:
            try:
                async with await conn.execute("SELECT next_payment_date FROM keys WHERE id = ?", (key_id,)) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return

                    current_end_str = row["next_payment_date"]
                    current_end = datetime.strptime(current_end_str, "%Y-%m-%d").date()
                    today = datetime.now(ZoneInfo("Europe/Moscow")).date()

                    new_date = today + timedelta(days=days) if current_end < today else current_end + timedelta(days=days)

                # Снимаем is_suspended и сохраняем обновленные настройки
                await conn.execute(
                    "UPDATE keys SET next_payment_date = ?, is_active = 1, is_suspended = 0, deactivated_at = NULL, settings = ? WHERE id = ?",
                    (new_date.strftime("%Y-%m-%d"), encrypt_data(new_settings), key_id),
                )
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error("db_transaction_failed", error=str(e))
                raise e

    async def upsert_user(self, tg_id: int, username: str) -> None:
        """Добавляет пользователя, если его нет, или обновляет юзернейм"""
        async with self.db.connect() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO users (tg_id, username) VALUES (?, ?)
                    ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username
                    """,
                    (tg_id, username),
                )
                await conn.commit()
            except Exception as e:
                    await conn.rollback()
                    logger.error("db_transaction_failed", error=str(e))
                    raise e

    async def add_key(
        self, tg_id: int, username: str, vless_key: str, price: int, payment_date: str, uuid: str, panel_host: str, inbound_id: int, settings: str | None = None
    ) -> None:
        async with self.db.connect() as conn:
            uuid_hash = get_uuid_hash(uuid)

            try:
                await conn.execute(
                    "INSERT INTO users (tg_id, username) VALUES (?, ?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
                    (tg_id, username),
                )
                # Вставляем uuid_hash вместе с остальными данными и указываем is_encrypted = 1
                await conn.execute(
                    "INSERT INTO keys (tg_id, vless_key, price, next_payment_date, uuid, panel_host, inbound_id, is_active, settings, uuid_hash, is_encrypted) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 1)",
                    (tg_id, encrypt_data(vless_key), price, payment_date, encrypt_data(uuid), panel_host, inbound_id, encrypt_data(settings) if settings else None, uuid_hash),
                )
                await conn.commit()

            except aiosqlite.IntegrityError as e:
                await conn.rollback()
                # ✅ Проверяем, что сработал именно наш уникальный индекс, а не какая-то другая ошибка БД
                if "keys.panel_host, keys.uuid_hash" in str(e) or "UNIQUE" in str(e):
                    raise ValueError(f"Активный ключ с UUID {uuid} уже существует на этом сервере!") from e
                raise e # Если это другая ошибка БД — бросаем её дальше

    async def get_id_by_username(self, username: str) -> int | None:
        async with self.db.connect() as conn:
            clean_name = username.replace("@", "")
            async with await conn.execute("SELECT tg_id FROM users WHERE username = ?", (clean_name,)) as cursor:
                row = await cursor.fetchone()
                return row["tg_id"] if row else None

    async def get_users_grouped(self) -> list[aiosqlite.Row]:
        async with self.db.connect() as conn:
            async with await conn.execute("""
                SELECT users.tg_id, users.username, COUNT(keys.id) as keys_count, SUM(keys.price) as total_price
                FROM users JOIN keys ON users.tg_id = keys.tg_id
                WHERE keys.is_active = 1 GROUP BY users.tg_id
            """) as cursor:
                return list(await cursor.fetchall())

    async def get_username(self, tg_id: int) -> str | None:
        async with self.db.connect() as conn:
            async with await conn.execute("SELECT username FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                row = await cursor.fetchone()
                return row["username"] if row else None

    async def get_all_active_keys(self) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            async with await conn.execute(
                "SELECT id, tg_id, price, next_payment_date, uuid, panel_host, inbound_id, settings FROM keys WHERE is_active = 1"
            ) as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["uuid"] = decrypt_data(d["uuid"])
                    d["settings"] = decrypt_data(d["settings"]) if d["settings"] else None
                    result.append(d)
                return result

    async def get_active_payment_rows(self) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            # Добавили last_notification_sent и is_suspended
            async with await conn.execute(
                "SELECT id, tg_id, price, next_payment_date, last_notification_sent, is_suspended FROM keys WHERE is_active = 1"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def delete_old_inactive_keys(self, days: int = 90) -> int:
        """Удаляет ключи, которые были деактивированы более N дней назад"""

        async with self.db.connect() as conn:

            cutoff = (
                datetime.now(ZoneInfo("Europe/Moscow")).date()
                - timedelta(days=days)
            ).strftime("%Y-%m-%d")

            cursor = await conn.execute(
                """
                DELETE FROM keys
                WHERE is_active = 0
                AND deactivated_at IS NOT NULL
                AND date(deactivated_at) <= date(?)
                """,
                (cutoff,),
            )

            deleted = int(cursor.rowcount)
            await conn.commit()

            return deleted

    async def update_vless_key(self, key_id: int, new_vless_key: str) -> None:
        """Обновляет ссылку на ключ конкретного пользователя."""
        async with self.db.connect() as conn:
            try:
                await conn.execute(
                    "UPDATE keys SET vless_key = ? WHERE id = ?",
                    (encrypt_data(new_vless_key), key_id)
                )
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error("db_transaction_failed", error=str(e))
                raise e

    async def bulk_replace_in_keys(self, old_str: str, new_str: str) -> list[tuple[int, int]]:
        """Безопасная массовая замена IP/Домена во всех активных ключах (Enterprise Level)."""
        async with self.db.connect() as conn:
            try:
                # 🔒 БЕЗОПАСНОСТЬ: Эксклюзивная блокировка БД (Write Lock) ДО начала чтения.
                # Исключает чтение одних и тех же данных параллельными транзакциями.
                await conn.execute("BEGIN IMMEDIATE")

                cursor = await conn.execute("SELECT id, tg_id, vless_key, panel_host FROM keys WHERE is_active = 1")
                rows = await cursor.fetchall()

                updated_keys = []
                for r in rows:
                    key_id = r["id"]
                    tg_id = r["tg_id"]
                    current_key = decrypt_data(r["vless_key"])
                    panel_host = r["panel_host"]

                    new_panel_host = new_str if panel_host == old_str else panel_host
                    new_key = current_key

                    try:
                        # Безопасный парсинг URL
                        parsed = urlparse(current_key)

                        netloc = parsed.netloc
                        if f"@{old_str}:" in netloc or netloc.endswith(f"@{old_str}"):
                            netloc = netloc.replace(f"@{old_str}", f"@{new_str}")

                        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                        for k, v in query_params.items():
                            if v == old_str:
                                query_params[k] = new_str

                        new_query = urlencode(query_params, safe="")

                        parsed = parsed._replace(netloc=netloc, query=new_query)
                        new_key = urlunparse(parsed)
                    except Exception as parse_e:
                        logger.error(f"Сбой парсинга URL для ключа {key_id}: {parse_e}")
                        continue

                    if new_key != current_key or new_panel_host != panel_host:
                        await conn.execute(
                            "UPDATE keys SET vless_key = ?, panel_host = ? WHERE id = ?",
                            (encrypt_data(new_key), new_panel_host, key_id)
                        )
                        updated_keys.append((key_id, tg_id))

                if updated_keys:
                    await conn.commit()

                return updated_keys

            except Exception as e:
                await conn.rollback()
                logger.error("db_transaction_failed", error=str(e))
                raise e

    async def rotate_encryption(self) -> int:
        """Перешифровывает все данные актуальным (первым) ключом из ENCRYPTION_KEY."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT id, vless_key, uuid, settings FROM keys")
            rows = await cursor.fetchall()

            updated = 0
            for r in rows:
                key_id = r["id"]
                try:
                    # decrypt_data прочитает любым валидным ключом из старых
                    raw_vless = decrypt_data(r["vless_key"]) if r["vless_key"] else None
                    raw_uuid = decrypt_data(r["uuid"]) if r["uuid"] else None
                    raw_settings = decrypt_data(r["settings"]) if r["settings"] else None

                    # encrypt_data всегда использует ПЕРВЫЙ (самый новый) ключ
                    await conn.execute(
                        "UPDATE keys SET vless_key = ?, uuid = ?, settings = ? WHERE id = ?",
                        (
                            encrypt_data(raw_vless) if raw_vless else None,
                            encrypt_data(raw_uuid) if raw_uuid else None,
                            encrypt_data(raw_settings) if raw_settings else None,
                            key_id
                        )
                    )
                    updated += 1
                except Exception as e:
                    logger.error(f"Сбой перешифровки ключа {key_id}: {e}")

            await conn.commit()
            return updated

    async def mark_notification_sent(self, key_id: int, date_str: str) -> None:
        """Обновляет дату последнего отправленного уведомления."""
        async with self.db.connect() as conn:
            try:
                await conn.execute("UPDATE keys SET last_notification_sent = ? WHERE id = ?", (date_str, key_id))
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error("db_transaction_failed", error=str(e))
                raise e

    async def set_suspended_status(self, key_id: int, is_suspended: bool, new_settings: str) -> None:
        """Обновляет статус блокировки (Grace Period) и сохраняет измененные настройки."""
        async with self.db.connect() as conn:
            try:
                await conn.execute(
                    "UPDATE keys SET is_suspended = ?, settings = ? WHERE id = ?",
                    (int(is_suspended), encrypt_data(new_settings), key_id)
                )
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error("db_transaction_failed", error=str(e))
                raise e
