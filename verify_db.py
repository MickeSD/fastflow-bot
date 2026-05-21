import asyncio

import aiosqlite

from core.config import BASE_DIR
from core.security import decrypt_data, get_uuid_hash


async def verify() -> None:
    db_path = BASE_DIR / "db_data" / "vpn_database.db"
    bad = []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # ✅ 1. Проверяем наличие NULL у активных ключей
        cursor = await db.execute("SELECT id FROM keys WHERE is_active = 1 AND uuid_hash IS NULL")
        null_rows = await cursor.fetchall()
        if null_rows:
            bad.append(("DB", f"Найдено {len(null_rows)} активных ключей с пустым uuid_hash!"))

        # ✅ 2. Глубокая верификация (расшифровка + сверка хешей)
        cursor = await db.execute("SELECT id, uuid, settings, uuid_hash FROM keys")
        rows = await cursor.fetchall()

        for row in rows:
            key_id = row["id"]
            try:
                raw_uuid = None
                if row["uuid"]:
                    raw_uuid = decrypt_data(row["uuid"])
                if row["settings"]:
                    decrypt_data(row["settings"])

                # Сверяем хеш в базе с тем, который получается из расшифрованного UUID
                if raw_uuid and row["uuid_hash"]:
                    expected_hash = get_uuid_hash(raw_uuid)
                    if expected_hash != row["uuid_hash"]:
                        bad.append((key_id, "Несовпадение хеша! Защита от дублей не работает."))
            except Exception as e:
                bad.append((key_id, str(e)))

    if bad:
        print("❌ Ошибки верификации базы данных:")
        for key_id, error in bad:
            print(f"ID {key_id}: {error}")
        raise SystemExit(1)

    print("✅ Супер! Все данные расшифровываются, хеши совпадают, NULL-дыр нет.")

if __name__ == "__main__":
    asyncio.run(verify())
