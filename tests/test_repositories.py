import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from infrastructure.repositories import KeyRepository

@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()

@pytest.fixture
def key_repo(mock_db: AsyncMock) -> KeyRepository:
    return KeyRepository(db=mock_db)

class FakeExecuteResult:
    """Универсальный мок, который поддерживает и `await` и `async with`"""
    def __init__(self, cursor_mock: AsyncMock):
        self.cursor_mock = cursor_mock
    def __await__(self):
        async def _awaitable():
            return self.cursor_mock
        return _awaitable().__await__()
    async def __aenter__(self):
        return self.cursor_mock
    async def __aexit__(self, exc_type, exc_val, exc_tb):
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
    # ✅ Теперь оба вызова execute (async with и await) пройдут успешно!
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
    mock_conn.commit.assert_called_once()

@pytest.mark.asyncio
async def test_get_all_active_keys(key_repo: KeyRepository, mock_db: AsyncMock) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [{"id": 1}]
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=FakeExecuteResult(mock_cursor))
    mock_db.connect = AsyncMock(return_value=mock_conn)
    
    res = await key_repo.get_all_active_keys()
    assert len(res) == 1