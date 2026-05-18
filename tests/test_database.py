from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.database import Database


@pytest.fixture
def db_instance() -> Database:
    return Database(db_path=":memory:")

@pytest.mark.asyncio
@patch("infrastructure.database.aiosqlite.connect", new_callable=AsyncMock)
async def test_db_connect_success(mock_connect: AsyncMock, db_instance: Database) -> None:
    """Тест: Успешное создание соединения с БД"""
    mock_conn = AsyncMock()
    mock_connect.return_value = mock_conn

    conn = await db_instance.connect()

    assert conn == mock_conn
    mock_connect.assert_called_once()
    mock_conn.execute.assert_any_call("PRAGMA journal_mode=WAL;")

@pytest.mark.asyncio
async def test_init_db_fails_without_key(db_instance: Database) -> None:
    """Тест: Падение инициализации при отсутствии ENCRYPTION_KEY"""
    with patch("infrastructure.database.ENCRYPTION_KEY", ""):
        with pytest.raises(RuntimeError, match="FATAL"):
            await db_instance.init_db()

@pytest.mark.asyncio
async def test_db_close(db_instance: Database) -> None:
    """Тест: Корректное закрытие соединения"""
    db_instance._conn = AsyncMock()
    await db_instance.close()
    assert db_instance._conn is None

@pytest.mark.asyncio
async def test_db_backup(db_instance: Database) -> None:
    """Тест: Создание резервной копии БД"""
    mock_conn = AsyncMock()
    mock_backup_db = AsyncMock()

    with patch.object(db_instance, 'connect', return_value=mock_conn):
        await db_instance.backup(mock_backup_db)
        mock_conn.backup.assert_called_once_with(mock_backup_db)
