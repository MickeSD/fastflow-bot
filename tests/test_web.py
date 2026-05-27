import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from infrastructure.web import (
    CONTAINER_KEY,
    check_auth,
    health_handler,
    metrics_handler,
    start_observability_server,
)


def test_check_auth_success() -> None:
    """Тест: Успешная авторизация hmac"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": settings.metrics_token}, "query": {}})()
    assert check_auth(request) is True

def test_check_auth_fail() -> None:
    """Тест: Провал авторизации (защита от тайминг-атак)"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": "fake"}, "query": {}})()
    assert check_auth(request) is False

def test_metrics_handler_wrong_token() -> None:
    """Тест: Неверный токен метрик"""
    request = type("Request", (), {"headers": {"X-Metrics-Token": "wrong"}, "query": {}})()
    # Сначала проверка auth, потом ответ
    with patch("infrastructure.web.check_auth", return_value=False):
        response = asyncio.run(metrics_handler(request))
        assert response.status == 401

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

    # Имитируем контекстный менеджер для БД
    mock_db_instance = MagicMock()
    mock_db_instance.connect.return_value.__aenter__.return_value = mock_db_connect

    mock_container = MagicMock()
    mock_container.db.return_value = mock_db_instance

    request = type("Request", (), {
        "headers": {"X-Metrics-Token": settings.metrics_token},
        "query": {},
        "app": {CONTAINER_KEY: mock_container}
    })()

    mock_r_client = AsyncMock()
    mock_r_client.ping = AsyncMock()
    mock_r_client.close = AsyncMock()
    mock_redis.return_value = mock_r_client

    response = await health_handler(request)

    assert response.status == 200
    data = json.loads(response.text or "{}")
    assert data["status"] == "ok"

@pytest.mark.asyncio
@patch("infrastructure.web.aioredis.from_url", new_callable=AsyncMock)
async def test_health_handler_redis_fail(mock_redis: AsyncMock) -> None:
    """Тест: Health-check возвращает 503, если Redis недоступен"""
    mock_db_connect = MagicMock()
    mock_db_connect.execute = AsyncMock()
    mock_db_instance = MagicMock()
    mock_db_instance.connect.return_value.__aenter__.return_value = mock_db_connect
    mock_container = MagicMock()
    mock_container.db.return_value = mock_db_instance

    request = type("Request", (), {
        "headers": {"X-Metrics-Token": settings.metrics_token},
        "query": {},
        "app": {CONTAINER_KEY: mock_container}
    })()

    # Имитируем падение Redis
    mock_redis.side_effect = Exception("Redis connection refused")
    response = await health_handler(request)

    assert response.status == 503
    data = json.loads(response.text or "{}")
    assert data["checks"]["redis"] == "fail"

@pytest.mark.asyncio
@patch("infrastructure.web.aiohttp.web.TCPSite", new_callable=MagicMock)
@patch("infrastructure.web.aiohttp.web.AppRunner.setup", new_callable=AsyncMock)
async def test_start_observability_server(mock_setup: AsyncMock, mock_tcpsite: MagicMock) -> None:
    mock_container = MagicMock()
    mock_site_instance = AsyncMock()
    mock_tcpsite.return_value = mock_site_instance

    runner = await start_observability_server(mock_container, 8080)

    try:
        assert runner is not None
        mock_setup.assert_called_once()
        mock_site_instance.start.assert_awaited_once()
    finally:
        await runner.cleanup() #✅ Добавили очистку, чтобы не было предупреждений
