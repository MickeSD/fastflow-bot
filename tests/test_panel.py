from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses

from services.panel import (
    PanelAPI,
    _safe_api_request,
    add_client_to_panel,
    delete_client_from_panel,
    update_client_in_panel,
)


@pytest.mark.asyncio
async def test_safe_api_request_success() -> None:
    """Тест: Успешный POST запрос"""
    panel = {"url": "http://fake-panel.com", "user": "admin", "pass": "admin"}

    with aioresponses() as m:
        m.post(
            "http://fake-panel.com/panel/api/inbounds/addClient",
            payload={"success": True},
        )

        result = await _safe_api_request(
            panel, "http://fake-panel.com/panel/api/inbounds/addClient"
        )
        assert result is True
        await PanelAPI.close()


@pytest.mark.asyncio
async def test_safe_api_request_retry_on_401() -> None:
    """Тест: Бот должен обновить куки при ошибке 401 и повторить запрос"""
    panel = {"url": "http://fake-panel.com", "user": "admin", "pass": "admin"}

    with aioresponses() as m:
        # 1-я попытка: Панель отвечает 401 (куки протухли)
        m.post("http://fake-panel.com/panel/api/inbounds/addClient", status=401)
        # Бот пойдет логиниться
        m.post("http://fake-panel.com/login", payload={"success": True})
        # 2-я попытка: Успех
        m.post(
            "http://fake-panel.com/panel/api/inbounds/addClient",
            payload={"success": True},
        )

        result = await _safe_api_request(
            panel, "http://fake-panel.com/panel/api/inbounds/addClient"
        )
        assert result is True
        await PanelAPI.close()

@pytest.mark.asyncio
@patch("services.panel.PANELS", {"test_host": {"url": "http://test"}})
@patch("services.panel._safe_api_request", new_callable=AsyncMock)
async def test_add_client_to_panel(mock_safe: AsyncMock) -> None:
    mock_safe.return_value = True
    res = await add_client_to_panel("test_host", 1, "uuid", "email")
    assert res is True
    mock_safe.assert_called_once()

@pytest.mark.asyncio
@patch("services.panel.PANELS", {"test_host": {"url": "http://test"}})
@patch("services.panel._safe_api_request", new_callable=AsyncMock)
async def test_update_client_in_panel(mock_safe: AsyncMock) -> None:
    mock_safe.return_value = True
    res = await update_client_in_panel("test_host", 1, "uuid", "email")
    assert res is True

@pytest.mark.asyncio
@patch("services.panel.PANELS", {"test_host": {"url": "http://test"}})
@patch("services.panel._safe_api_request", new_callable=AsyncMock)
async def test_delete_client_from_panel(mock_safe: AsyncMock) -> None:
    mock_safe.return_value = True
    res = await delete_client_from_panel("test_host", 1, "uuid")
    assert res is True
