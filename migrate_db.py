import asyncio

import aiosqlite

from core.config import BASE_DIR
from core.security import encrypt_data


async def migrate() -> None:
    db_path = BASE_DIR / "db_data" / "vpn_database.db"
    print(f"Подключаемся к БД: {db_path}")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Строго берем только незашифрованные строки по флагу
        cursor = await db.execute("SELECT id, uuid, settings FROM keys WHERE is_encrypted = 0")
        rows = await cursor.fetchall()

        updated = 0
        for r in rows:
            key_id = r["id"]
            uuid = r["uuid"]
            settings = r["settings"]

            new_uuid = encrypt_data(uuid) if uuid else uuid
            new_settings = encrypt_data(settings) if settings else settings

            try:
                await db.execute(
                    "UPDATE keys SET uuid = ?, settings = ?, is_encrypted = 1 WHERE id = ?",
                    (new_uuid, new_settings, key_id)
                )
                updated += 1
            except Exception as e:
                print(f"Ошибка при шифровании ключа {key_id}: {e}")
                await db.rollback()
                raise e

        await db.commit()
        print(f"✅ Миграция завершена. Успешно зашифровано старых записей: {updated}")

if __name__ == "__main__":
    asyncio.run(migrate())
