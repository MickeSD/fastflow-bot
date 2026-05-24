from datetime import datetime, timedelta
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

import aiosqlite

from core.security import decrypt_data, encrypt_data, get_uuid_hash
from infrastructure.database import Database


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
        conn = await self.db.connect()
        async with conn.execute("SELECT * FROM keys WHERE id = ?", (key_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                row_dict = dict(row)
                row_dict["vless_key"] = decrypt_data(row_dict["vless_key"])
                row_dict["uuid"] = decrypt_data(row_dict["uuid"])
                row_dict["settings"] = decrypt_data(row_dict["settings"]) if row_dict["settings"] else None
                return row_dict
            return None

    async def get_user_keys(self, tg_id: int) -> list[KeyRecord]:
        conn = await self.db.connect()
        async with conn.execute("SELECT * FROM keys WHERE tg_id = ? AND is_active = 1", (tg_id,)) as cursor:
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
        conn = await self.db.connect()
        now_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
        await conn.execute(
            "UPDATE keys SET is_active = 0, deactivated_at = ? WHERE id = ?",
            (now_str, key_id),
        )
        await conn.commit()

    async def extend_subscription(self, key_id: int, days: int) -> None:
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT next_payment_date FROM keys WHERE id = ?", (key_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return

            current_end_str = row["next_payment_date"]
            current_end = datetime.strptime(current_end_str, "%Y-%m-%d").date()
            today = datetime.now(ZoneInfo("Europe/Moscow")).date()

            new_date = today + timedelta(days=days) if current_end < today else current_end + timedelta(days=days)

            await conn.execute(
                "UPDATE keys SET next_payment_date = ?, is_active = 1, deactivated_at = NULL WHERE id = ?",
                (new_date.strftime("%Y-%m-%d"), key_id),
            )
            await conn.commit()

    async def upsert_user(self, tg_id: int, username: str) -> None:
        """Добавляет пользователя, если его нет, или обновляет юзернейм"""
        conn = await self.db.connect()
        await conn.execute(
            """
            INSERT INTO users (tg_id, username) VALUES (?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username
            """,
            (tg_id, username),
        )
        await conn.commit()

    async def add_key(
        self, tg_id: int, username: str, vless_key: str, price: int, payment_date: str, uuid: str, panel_host: str, inbound_id: int, settings: str | None = None
    ) -> None:
        conn = await self.db.connect()
        uuid_hash = get_uuid_hash(uuid)

        try:
            await conn.execute(
                "INSERT INTO users (tg_id, username) VALUES (?, ?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
                (tg_id, username),
            )
            # Вставляем uuid_hash вместе с остальными данными
            await conn.execute(
                "INSERT INTO keys (tg_id, vless_key, price, next_payment_date, uuid, panel_host, inbound_id, is_active, settings, uuid_hash) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
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
        conn = await self.db.connect()
        clean_name = username.replace("@", "")
        async with conn.execute("SELECT tg_id FROM users WHERE username = ?", (clean_name,)) as cursor:
            row = await cursor.fetchone()
            return row["tg_id"] if row else None

    async def get_users_grouped(self) -> list[aiosqlite.Row]:
        conn = await self.db.connect()
        async with conn.execute("""
            SELECT users.tg_id, users.username, COUNT(keys.id) as keys_count, SUM(keys.price) as total_price
            FROM users JOIN keys ON users.tg_id = keys.tg_id
            WHERE keys.is_active = 1 GROUP BY users.tg_id
        """) as cursor:
            return list(await cursor.fetchall())

    async def get_username(self, tg_id: int) -> str | None:
        conn = await self.db.connect()
        async with conn.execute("SELECT username FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            return row["username"] if row else None

    async def get_all_active_keys(self) -> list[dict[str, Any]]:
        conn = await self.db.connect()
        async with conn.execute(
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
        """Легкий метод для планировщика: без расшифровки секретов"""
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT id, tg_id, price, next_payment_date FROM keys WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def delete_old_inactive_keys(self, days: int = 90) -> int:
        """Удаляет ключи, которые были деактивированы более N дней назад"""

        conn = await self.db.connect()

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

        deleted = cursor.rowcount
        await conn.commit()

        return deleted

    async def update_vless_key(self, key_id: int, new_vless_key: str) -> None:
        """Обновляет ссылку на ключ конкретного пользователя."""
        conn = await self.db.connect()
        await conn.execute(
            "UPDATE keys SET vless_key = ? WHERE id = ?",
            (encrypt_data(new_vless_key), key_id)
        )
        await conn.commit()

    async def bulk_replace_in_keys(self, old_str: str, new_str: str) -> list[tuple[int, int]]:
        """Массовая замена подстроки (например, IP на SNI) во всех активных ключах."""
        conn = await self.db.connect()
        cursor = await conn.execute("SELECT id, tg_id, vless_key FROM keys WHERE is_active = 1")
        rows = await cursor.fetchall()

        updated_keys = []
        for r in rows:
            key_id = r["id"]
            tg_id = r["tg_id"]
            current_key = decrypt_data(r["vless_key"])

            # Если искомая строка есть в ссылке — меняем и перезаписываем
            if old_str in current_key:
                new_key = current_key.replace(old_str, new_str)
                await conn.execute(
                    "UPDATE keys SET vless_key = ? WHERE id = ?",
                    (encrypt_data(new_key), key_id)
                )
                updated_keys.append((key_id, tg_id))

        if updated_keys:
            await conn.commit()

        return updated_keys