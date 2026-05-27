from typing import Any, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.repositories import KeyRepository


@pytest.fixture
def repo_mock_db() -> Tuple[KeyRepository, AsyncMock]:
    db = MagicMock()
    conn = AsyncMock()
    db.connect.return_value.__aenter__.return_value = conn
    return KeyRepository(db), conn


@pytest.mark.asyncio
async def test_repo_exceptions_trigger_rollback(repo_mock_db: Tuple[KeyRepository, AsyncMock]) -> None:
    """Тест: Операции с await conn.execute вызывают rollback при ошибке"""
    repo, conn = repo_mock_db

    # Настраиваем execute для вызовов: await conn.execute(...)
    conn.execute = AsyncMock(side_effect=Exception("Artificial DB Error"))

    funcs = [
        repo.deactivate_key(1),
        repo.upsert_user(1, "user"),
        repo.update_vless_key(1, "key"),
        repo.bulk_replace_in_keys("old", "new"),
        repo.mark_notification_sent(1, "2026-01-01"),
        repo.set_suspended_status(1, True, "{}")
    ]

    for i, func in enumerate(funcs, 1):
        with pytest.raises(Exception, match="Artificial DB Error"):
            await func
        assert conn.rollback.call_count == i


@pytest.mark.asyncio
async def test_extend_subscription_rollback(repo_mock_db: Tuple[KeyRepository, AsyncMock]) -> None:
    """Тест: Операции с async with conn.execute вызывают rollback при ошибке"""
    repo, conn = repo_mock_db

    class FailingCursor:
        async def __aenter__(self) -> Any:
            raise Exception("Artificial DB Error")
        async def __aexit__(self, *args: Any) -> None:
            pass

    # Поскольку в коде теперь `await conn.execute(...)`,
    # мы просто заставляем AsyncMock вернуть наш падающий курсор.
    conn.execute.return_value = FailingCursor()

    with pytest.raises(Exception, match="Artificial DB Error"):
        await repo.extend_subscription(1, 30, "{}")

    assert conn.rollback.call_count == 1
