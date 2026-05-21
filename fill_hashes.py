import asyncio

import aiosqlite

from core.config import BASE_DIR
from core.security import decrypt_data, get_uuid_hash


async def run() -> None:
    db_path = BASE_DIR / "db_data" / "vpn_database.db"
    errors = []
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Берем ВСЕ ключи (убираем WHERE uuid_hash IS NULL), так как нам нужно пересобрать хеши с новым секретом
        cursor = await db.execute("SELECT id, uuid FROM keys")
        rows = await cursor.fetchall()

        updated = 0
        for r in rows:
            key_id = r["id"]
            encrypted_uuid = r["uuid"]
            if encrypted_uuid:
                try:
                    raw_uuid = decrypt_data(encrypted_uuid)
                    hash_val = get_uuid_hash(raw_uuid)
                    await db.execute("UPDATE keys SET uuid_hash = ? WHERE id = ?", (hash_val, key_id))
                    updated += 1
                except Exception as e:
                    errors.append((key_id, str(e)))

        # ✅ Fail-hard: если хоть одна ошибка — откатываем ВСЁ
        if errors:
            await db.rollback()
            print("❌ Критические ошибки при генерации хешей. Изменения отменены!")
            for key_id, err in errors:
                print(f"ID {key_id}: {err}")
            raise SystemExit(1)

        await db.commit()
        print(f"✅ Готово! Успешно обновлено/создано хешей: {updated}")

if __name__ == "__main__":
    asyncio.run(run())
