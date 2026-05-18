from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.repositories import KeyRepository


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()

@pytest.fixture
def key_repo(mock_db: AsyncMock) -> KeyRepository:
    return KeyRepository(db=mock_db)

class FakeExecuteResult:
    """Универсальный мок, который поддерживает и `await` и `async with`"""
    def __init__(self, cursor_mock: AsyncMock) -> None:
        self.cursor_mock = cursor_mock

    def __await__(self) -> Generator[Any, None, Any]:
        async def _awaitable() -> AsyncMock:
            return self.cursor_mock
        return _awaitable().__await__()

    async def __aenter__(self) -> AsyncMock:
        return self.cursor_mock

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

@pytest.mark.asyncio
async def test_get_username_found(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = {"username": "misha_dugin"}

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)

    result = await key_repo.get_username(12345)
    assert result == "misha_dugin"
    mock_conn.execute.assert_called_once()

@pytest.mark.asyncio
async def test_deactivate_key(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(AsyncMock()))
    mock_conn.commit = AsyncMock()
    mock_db.connect = AsyncMock(return_value=mock_conn)

    await key_repo.deactivate_key(99)
    mock_conn.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_user_keys(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [
        {"id": 1, "tg_id": 123, "vless_key": "encoded", "price": 100, "next_payment_date": "2025-01-01",
         "panel_host": "host", "inbound_id": 1, "is_active": 1, "settings": "{}", "deactivated_at": None}
    ]
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)

    with patch("infrastructure.repositories.decrypt_data", return_value="decoded"):
        res = await key_repo.get_user_keys(123)

    assert len(res) == 1
    assert res[0]["vless_key"] == "decoded"

@pytest.mark.asyncio
async def test_extend_subscription(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = {"next_payment_date": "2026-05-18"}

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_conn.commit = AsyncMock()
    mock_db.connect = AsyncMock(return_value=mock_conn)

    await key_repo.extend_subscription(1, 30)
    assert mock_conn.execute.call_count == 2
    mock_conn.commit.assert_called_once()

@pytest.mark.asyncio
async def test_upsert_user(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(AsyncMock()))
    mock_conn.commit = AsyncMock()
    mock_db.connect = AsyncMock(return_value=mock_conn)

    await key_repo.upsert_user(123, "test")
    mock_conn.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_all_active_keys(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [{"id": 1}]
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)

    res = await key_repo.get_all_active_keys()
    assert len(res) == 1

# === НОВЫЕ ТЕСТЫ ДЛЯ ПОКРЫТИЯ ===

@pytest.mark.asyncio
async def test_get_id_by_username(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    """Тест: Поиск ID по юзернейму"""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = {"tg_id": 777}
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)

    res = await key_repo.get_id_by_username("@testuser")
    assert res == 777

@pytest.mark.asyncio
async def test_get_users_grouped(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    """Тест: Выгрузка статистики пользователей"""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [{"tg_id": 1}]
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)

    res = await key_repo.get_users_grouped()
    assert len(res) == 1

@pytest.mark.asyncio
async def test_delete_old_inactive_keys(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    """Тест: Очистка старых ключей (Cron)"""
    mock_cursor = AsyncMock()
    mock_cursor.rowcount = 10
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_conn.commit = AsyncMock()
    mock_db.connect = AsyncMock(return_value=mock_conn)

    deleted = await key_repo.delete_old_inactive_keys(90)
    assert deleted == 10

@pytest.mark.asyncio
async def test_add_key(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    """Тест: Добавление нового ключа"""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None # Симулируем, что дубликатов нет
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_conn.commit = AsyncMock()
    mock_db.connect = AsyncMock(return_value=mock_conn)

    await key_repo.add_key(1, "test", "vless://", 100, "2026-01-01", "uuid", "host", 1, "{}")
    assert mock_conn.execute.call_count == 3 # SELECT (проверка дублей), INSERT users, INSERT keys
    mock_conn.commit.assert_called_once()
