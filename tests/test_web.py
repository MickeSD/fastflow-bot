import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from infrastructure.web import check_auth, health_handler, metrics_handler


def test_check_auth_success() -> None:
    """Тест: Успешная авторизация hmac"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": settings.metrics_token}, "query": {}})()
    assert check_auth(request) is True

def test_check_auth_fail() -> None:
    """Тест: Провал авторизации (защита от тайминг-атак)"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": "fake"}, "query": {}})()
    assert check_auth(request) is False

@pytest.mark.asyncio
@patch("infrastructure.web.generate_latest", return_value=b"test_metrics")
async def test_metrics_handler_authorized(mock_generate: MagicMock) -> None:
    """Тест: Успешный возврат метрик"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": settings.metrics_token}, "query": {}})()
    response = await metrics_handler(request)
    assert response.status == 200

@pytest.mark.asyncio
async def test_metrics_handler_unauthorized() -> None:
    """Тест: Отказ в доступе к метрикам"""
    request = type("Request", (), {"headers": {}, "query": {}})()
    response = await metrics_handler(request)
    assert response.status == 401

@pytest.mark.asyncio
@patch("infrastructure.web.aioredis.from_url", new_callable=AsyncMock)
async def test_health_handler_success(mock_redis: AsyncMock) -> None:
    """Тест: Успешный Health-check (БД + Redis)"""
    mock_db_connect = MagicMock()
    mock_db_connect.execute = AsyncMock()

    mock_db_instance = MagicMock()
    mock_db_instance.connect = AsyncMock(return_value=mock_db_connect)

    mock_container = MagicMock()
    mock_container.db.return_value = mock_db_instance

    request = type("Request", (), {
        "headers": {"X-Metrics-Token": settings.metrics_token},
        "query": {},
        "app": {"container": mock_container}
    })()

    mock_r_client = AsyncMock()
    mock_r_client.ping = AsyncMock()
    mock_r_client.close = AsyncMock()
    mock_redis.return_value = mock_r_client

    response = await health_handler(request)

    assert response.status == 200
    # ✅ Утихомирили Mypy, гарантировав строку
    data = json.loads(response.text or "{}")
    assert data["status"] == "ok"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["redis"] == "ok"
