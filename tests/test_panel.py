import pytest
from aioresponses import aioresponses

from services.panel import PanelAPI, _safe_api_request


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
