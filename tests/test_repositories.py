import os
import tempfile
from typing import AsyncGenerator

import pytest

from infrastructure.database import Database
from infrastructure.repositories import KeyRepository


@pytest.fixture
async def real_db() -> AsyncGenerator[Database, None]:
    """Создает реальную временную SQLite базу для интеграционных тестов."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(path)
    conn = await db.connect()

    # Имитируем миграции Alembic (создаем реальную структуру)
    await conn.execute("CREATE TABLE users (tg_id INTEGER PRIMARY KEY, username TEXT)")
    await conn.execute("""
        CREATE TABLE keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, vless_key TEXT,
            price INTEGER, next_payment_date DATE, uuid TEXT, panel_host TEXT,
            inbound_id INTEGER, is_active BOOLEAN DEFAULT 1, settings TEXT,
            deactivated_at TEXT, uuid_hash TEXT, FOREIGN KEY(tg_id) REFERENCES users(tg_id)
        )
    """)
    # ✅ Тот самый уникальный индекс для защиты от гонки данных!
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
    """Тест: Успешное добавление и аппаратная защита SQLite от дублей."""

    # 1. Успешное добавление первого ключа
    await repo.add_key(
        tg_id=123, username="test_user", vless_key="vless://...",
        price=100, payment_date="2026-10-10", uuid="test-uuid-1",
        panel_host="host1", inbound_id=1, settings="{}"
    )
    keys = await repo.get_user_keys(123)
    assert len(keys) == 1
    assert keys[0]["panel_host"] == "host1"

    # 2. Пытаемся добавить дубликат (имитация Race Condition)
    # База должна отбить его на уровне UNIQUE constraints!
    with pytest.raises(ValueError, match="уже существует на этом сервере"):
        await repo.add_key(
            tg_id=999, username="hacker", vless_key="vless://fake",
            price=0, payment_date="2026-10-10", uuid="test-uuid-1", # Тот же UUID!
            panel_host="host1", inbound_id=1, settings="{}"
        )
