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
    # Имитируем контекстный менеджер aiosqlite
    mock_connect.return_value.__aenter__.return_value = mock_conn

    async with db_instance.connect() as conn:
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
    await db_instance.close()

@pytest.mark.asyncio
async def test_db_backup(db_instance: Database) -> None:
    """Тест: Создание резервной копии БД"""
    mock_conn = AsyncMock()
    mock_backup_db = AsyncMock()

    cm_mock = AsyncMock()
    cm_mock.__aenter__.return_value = mock_conn

    with patch.object(db_instance, 'connect', return_value=cm_mock):
        await db_instance.backup(mock_backup_db)
        mock_conn.backup.assert_called_once_with(mock_backup_db)
