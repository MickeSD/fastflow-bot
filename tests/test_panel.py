from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses

from services.panel import (
    PanelAPI,
    PanelService,
    _safe_api_request,
)


@pytest.fixture
def service() -> PanelService:
    return PanelService()

@pytest.mark.asyncio
async def test_safe_api_request_success() -> None:
    panel = {"url": "http://fake-panel.com", "user": "admin", "pass": "admin"}
    with aioresponses() as m:
        m.post("http://fake-panel.com/panel/api/inbounds/addClient", payload={"success": True})
        result = await _safe_api_request(panel, "http://fake-panel.com/panel/api/inbounds/addClient")
        assert result is True
        await PanelAPI.close()

@pytest.mark.asyncio
async def test_safe_api_request_retry_on_401() -> None:
    panel = {"url": "http://fake-panel.com", "user": "admin", "pass": "admin"}
    with aioresponses() as m:
        m.post("http://fake-panel.com/panel/api/inbounds/addClient", status=401)
        m.post("http://fake-panel.com/login", payload={"success": True})
        m.post("http://fake-panel.com/panel/api/inbounds/addClient", payload={"success": True})
        result = await _safe_api_request(panel, "http://fake-panel.com/panel/api/inbounds/addClient")
        assert result is True
        await PanelAPI.close()

@pytest.mark.asyncio
@patch("services.panel.PANELS", {"test_host": {"url": "http://test"}})
@patch("services.panel._safe_api_request", new_callable=AsyncMock)
async def test_panel_service_success(mock_safe: AsyncMock) -> None:
    """Проверка успешных вызовов PanelService"""
    mock_safe.return_value = True
    service = PanelService()

    assert await service.add_client("test_host", 1, "uuid", "email") is True
    assert await service.update_client("test_host", 1, "uuid", "email") is True
    assert await service.delete_client("test_host", 1, "uuid") is True
    assert await service.inbound_exists("test_host", 1) is True

@pytest.mark.asyncio
@patch("services.panel.PANELS", {"test_host": {"url": "http://test"}})
@patch("services.panel._safe_api_request", new_callable=AsyncMock)
async def test_panel_service_exceptions(mock_safe: AsyncMock) -> None:
    """Проверка обработки исключений и несуществующих панелей в PanelService"""
    mock_safe.side_effect = Exception("API Down")
    service = PanelService()

    # Узел падает с ошибкой
    assert await service.add_client("test_host", 1, "uuid", "email") is False
    assert await service.update_client("test_host", 1, "uuid", "email") is False
    assert await service.delete_client("test_host", 1, "uuid") is False
    assert await service.inbound_exists("test_host", 1) is None

    # Узел вообще не найден в конфиге
    assert await service.add_client("wrong_host", 1, "uuid", "email") is False

@pytest.mark.asyncio
async def test_panel_service_wrong_host(service: PanelService) -> None:
    assert await service.add_client("nonexistent", 1, "u", "e") is False

@pytest.mark.asyncio
@patch("services.panel.PANELS", {}) # Панели пусты
async def test_panel_service_no_config(service: PanelService) -> None:
    assert await service.add_client("unknown", 1, "u", "e") is False
    assert await service.update_client("unknown", 1, "u", "e") is False
    assert await service.delete_client("unknown", 1, "u") is False
    assert await service.inbound_exists("unknown", 1) is False
