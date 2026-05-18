import asyncio

import aiosqlite

from core.config import BASE_DIR
from core.security import encrypt_data


async def migrate() -> None:
    db_path = BASE_DIR / "db_data" / "vpn_database.db"
    print(f"Подключаемся к БД: {db_path}")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id, uuid, settings FROM keys")
        rows = await cursor.fetchall()

        updated = 0
        for r in rows:
            key_id = r["id"]
            uuid = r["uuid"]
            settings = r["settings"]

            new_uuid = uuid
            new_settings = settings

            # Токены Fernet всегда начинаются с gAAAAA, так мы понимаем, что текст еще не зашифрован
            if uuid and not uuid.startswith("gAAAAA"):
                new_uuid = encrypt_data(uuid)

            if settings and not settings.startswith("gAAAAA"):
                new_settings = encrypt_data(settings)

            if new_uuid != uuid or new_settings != settings:
                await db.execute("UPDATE keys SET uuid = ?, settings = ? WHERE id = ?", (new_uuid, new_settings, key_id))
                updated += 1

        await db.commit()
        print(f"✅ Миграция завершена. Успешно зашифровано старых записей: {updated}")

if __name__ == "__main__":
    asyncio.run(migrate())
