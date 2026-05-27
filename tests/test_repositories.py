import os
import tempfile
from datetime import datetime, timedelta
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

import pytest

from infrastructure.database import Database
from infrastructure.repositories import KeyRepository


@pytest.fixture
async def real_db() -> AsyncGenerator[Database, None]:
    """Создает реальную временную SQLite базу для интеграционных тестов."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(path)

    async with db.connect() as conn:
        await conn.execute("CREATE TABLE users (tg_id INTEGER PRIMARY KEY, username TEXT)")
        # Полная схема БД с учетом всех миграций (включая Hardening)
        await conn.execute("""
            CREATE TABLE keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, vless_key TEXT,
                price INTEGER, next_payment_date DATE, uuid TEXT, panel_host TEXT,
                inbound_id INTEGER, is_active BOOLEAN DEFAULT 1, settings TEXT,
                deactivated_at TEXT, uuid_hash TEXT, is_encrypted BOOLEAN DEFAULT 0,
                is_suspended BOOLEAN DEFAULT 0, last_notification_sent TEXT,
                FOREIGN KEY(tg_id) REFERENCES users(tg_id)
            )
        """)
        await conn.execute("CREATE UNIQUE INDEX idx_keys_active_uuid_hash_panel ON keys (panel_host, uuid_hash) WHERE is_active = 1")
        await conn.commit()

    yield db

    await db.close()
    os.remove(path)

@pytest.fixture
def repo(real_db: Database) -> KeyRepository:
    return KeyRepository(real_db)


@pytest.mark.asyncio
async def test_add_key_integration_and_race_condition(repo: KeyRepository) -> None:
    await repo.add_key(
        tg_id=123, username="test_user", vless_key="vless://...",
        price=100, payment_date="2026-10-10", uuid="test-uuid-1",
        panel_host="host1", inbound_id=1, settings="{}"
    )
    keys = await repo.get_user_keys(123)
    assert len(keys) == 1
    assert keys[0]["panel_host"] == "host1"

    with pytest.raises(ValueError, match="уже существует на этом сервере"):
        await repo.add_key(
            tg_id=999, username="hacker", vless_key="vless://fake",
            price=0, payment_date="2026-10-10", uuid="test-uuid-1",
            panel_host="host1", inbound_id=1, settings="{}"
        )

@pytest.mark.asyncio
async def test_user_operations(repo: KeyRepository) -> None:
    """Тестируем создание пользователя, обновление юзернейма и поиск."""
    await repo.upsert_user(1, "test_user")
    await repo.upsert_user(1, "test_updated") # Проверка ON CONFLICT

    assert await repo.get_username(1) == "test_updated"
    assert await repo.get_id_by_username("test_updated") == 1
    assert await repo.get_id_by_username("@test_updated") == 1 # Проверка очистки @
    assert await repo.get_id_by_username("not_exist") is None

@pytest.mark.asyncio
async def test_key_crud_lifecycle(repo: KeyRepository) -> None:
    """Полный жизненный цикл ключа: чтение, продление, блокировка, удаление."""
    await repo.upsert_user(1, "user1")
    await repo.add_key(1, "user1", "vless://key1", 100, "2026-10-10", "uuid1", "host1", 1, "{}")

    keys = await repo.get_user_keys(1)
    key_id = keys[0]["id"]

    # 1. Чтение
    info = await repo.get_key_info(key_id)
    assert info is not None
    assert info["panel_host"] == "host1"

    # 2. Продление
    await repo.extend_subscription(key_id, 30, '{"new": "settings"}')
    info2 = await repo.get_key_info(key_id)
    assert info2 is not None
    assert info2["settings"] == '{"new": "settings"}'
    assert info2["is_suspended"] == 0

    # 3. Маркировка уведомления и приостановка
    await repo.mark_notification_sent(key_id, "2026-05-26")
    await repo.set_suspended_status(key_id, True, '{"enable": false}')

    info3 = await repo.get_key_info(key_id)
    assert info3 is not None
    assert info3["is_suspended"] == 1
    assert info3["last_notification_sent"] == "2026-05-26"
    assert info3["settings"] == '{"enable": false}'

    # 4. Деактивация
    await repo.deactivate_key(key_id)
    info4 = await repo.get_key_info(key_id)
    assert info4 is not None
    assert info4["is_active"] == 0
    assert info4["deactivated_at"] is not None

@pytest.mark.asyncio
async def test_bulk_replace_in_keys(repo: KeyRepository) -> None:
    """Тестируем замену IP/домена через парсинг URL."""
    await repo.upsert_user(1, "user1")
    old_url = "vless://uuid@1.1.1.1:443?sni=1.1.1.1&type=tcp"
    await repo.add_key(1, "user1", old_url, 100, "2026-10-10", "uuid1", "1.1.1.1", 1, "{}")

    updated = await repo.bulk_replace_in_keys("1.1.1.1", "fastflow.com")
    assert len(updated) == 1

    keys = await repo.get_user_keys(1)
    new_vless = keys[0]["vless_key"]
    assert "fastflow.com" in new_vless
    assert "1.1.1.1" not in new_vless
    assert keys[0]["panel_host"] == "fastflow.com"

@pytest.mark.asyncio
async def test_get_users_grouped(repo: KeyRepository) -> None:
    """Тест группировки пользователей для админского отчета."""
    await repo.add_key(1, "user1", "vless://1", 100, "2026-10-10", "u1", "h1", 1)
    await repo.add_key(1, "user1", "vless://2", 150, "2026-10-10", "u2", "h2", 1)
    await repo.add_key(2, "user2", "vless://3", 200, "2026-10-10", "u3", "h1", 1)

    grouped = await repo.get_users_grouped()
    assert len(grouped) == 2
    user1_data = next(u for u in grouped if dict(u)["tg_id"] == 1)
    assert dict(user1_data)["keys_count"] == 2
    assert dict(user1_data)["total_price"] == 250

@pytest.mark.asyncio
async def test_delete_old_inactive_keys(repo: KeyRepository) -> None:
    """Проверка автоматической очистки базы."""
    await repo.add_key(1, "user1", "vless://1", 100, "2026-10-10", "u1", "h1", 1)
    keys = await repo.get_user_keys(1)
    key_id = keys[0]["id"]
    await repo.deactivate_key(key_id)

    # Искусственно состариваем дату деактивации на 100 дней
    old_date = (datetime.now(ZoneInfo("Europe/Moscow")) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    async with repo.db.connect() as conn:
        await conn.execute("UPDATE keys SET deactivated_at = ? WHERE id = ?", (old_date, key_id))
        await conn.commit()

    deleted = await repo.delete_old_inactive_keys(90)
    assert deleted == 1
    assert await repo.get_key_info(key_id) is None

@pytest.mark.asyncio
async def test_rotate_encryption(repo: KeyRepository) -> None:
    """Проверка ротации ключей шифрования."""
    await repo.add_key(1, "user1", "vless://1", 100, "2026-10-10", "u1", "h1", 1, "{}")
    updated = await repo.rotate_encryption()
    assert updated == 1

@pytest.mark.asyncio
async def test_repo_getters(repo: KeyRepository) -> None:
    await repo.upsert_user(1, "test_user")
    assert await repo.get_username(1) == "test_user"
    assert await repo.get_id_by_username("test_user") == 1

    await repo.add_key(1, "user1", "vless://1", 100, "2026-10-10", "u1", "h1", 1)
    active = await repo.get_all_active_keys()
    assert len(active) == 1

@pytest.mark.asyncio
async def test_repo_edge_cases(repo: KeyRepository) -> None:
    """Покрываем недостающие ветки в репозиториях."""
    # 1. Покрываем случай, когда get_username вернул None (логика в репозитории)
    assert await repo.get_username(99999) is None

    # 2. Покрываем случай, когда get_id_by_username не нашел юзера
    assert await repo.get_id_by_username("nonexistent") is None

    # 3. Покрываем случай, когда delete_old_inactive_keys ничего не удаляет
    deleted = await repo.delete_old_inactive_keys(90)
    assert deleted == 0
