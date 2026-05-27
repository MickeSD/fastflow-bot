from unittest.mock import AsyncMock

import pytest

from application.services.vpn import VpnService


@pytest.fixture
def mock_key_repo() -> AsyncMock:
    return AsyncMock()

@pytest.fixture
def mock_panel_service() -> AsyncMock:
    return AsyncMock()

@pytest.fixture
def vpn_service(mock_key_repo: AsyncMock, mock_panel_service: AsyncMock) -> VpnService:
    return VpnService(key_repo=mock_key_repo, panel_service=mock_panel_service)

@pytest.mark.asyncio
async def test_extend_key_not_found(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = None
    success, msg = await vpn_service.extend_key(1, 30)
    assert success is False

@pytest.mark.asyncio
async def test_extend_key_inbound_missing(vpn_service: VpnService, mock_key_repo: AsyncMock, mock_panel_service: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = {
        "panel_host": "test_host", "inbound_id": 1, "is_active": True, "settings": "{}"
    }
    mock_panel_service.inbound_exists.return_value = False
    success, msg = await vpn_service.extend_key(1, 30)
    assert success is False

@pytest.mark.asyncio
async def test_extend_key_success(vpn_service: VpnService, mock_key_repo: AsyncMock, mock_panel_service: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = {
        "panel_host": "host", "inbound_id": 1, "is_active": True,
        "uuid": "uuid123", "tg_id": 999, "settings": "{}"
    }
    mock_panel_service.inbound_exists.return_value = True
    mock_panel_service.update_client.return_value = True

    success, msg = await vpn_service.extend_key(1, 30)
    assert success is True
    mock_key_repo.extend_subscription.assert_called_once()

@pytest.mark.asyncio
async def test_cancel_subscription_wrong_user(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = {"tg_id": 111}
    success, msg = await vpn_service.cancel_subscription(1, 999)
    assert success is False

@pytest.mark.asyncio
async def test_cancel_subscription_success(vpn_service: VpnService, mock_key_repo: AsyncMock, mock_panel_service: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = {
        "tg_id": 999, "is_active": True, "settings": '{"email": "test@test"}',
        "uuid": "uuid", "panel_host": "host", "inbound_id": 1
    }
    mock_panel_service.delete_client.return_value = True
    success, msg = await vpn_service.cancel_subscription(1, 999)
    assert success is True
    mock_key_repo.deactivate_key.assert_called_once_with(1)

@pytest.mark.asyncio
async def test_suspend_subscription_not_found(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Попытка заморозить несуществующий ключ"""
    mock_key_repo.get_key_info.return_value = None
    success = await vpn_service.suspend_subscription(1)
    assert success is False

@pytest.mark.asyncio
async def test_suspend_subscription_success(vpn_service: VpnService, mock_key_repo: AsyncMock, mock_panel_service: AsyncMock) -> None:
    """Тест: Успешная заморозка (Grace Period)"""
    mock_key_repo.get_key_info.return_value = {
        "tg_id": 1, "panel_host": "host", "inbound_id": 1, "uuid": "uuid", "settings": "{}"
    }
    mock_panel_service.update_client.return_value = True
    success = await vpn_service.suspend_subscription(1)
    assert success is True
    mock_key_repo.set_suspended_status.assert_called_once()

@pytest.mark.asyncio
async def test_extend_key_json_error(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    mock_key_repo.get_key_info.return_value = {
        "panel_host": "host", "inbound_id": 1, "is_active": True,
        "uuid": "u", "tg_id": 1, "settings": "invalid_json"
    }
    # Функция должна вернуть False при ошибке парсинга
    success, msg = await vpn_service.extend_key(1, 30)
    assert success is False

@pytest.mark.asyncio
async def test_cancel_subscription_invalid_json(
    vpn_service: VpnService,
    mock_key_repo: AsyncMock,
    mock_panel_service: AsyncMock
) -> None:
    mock_key_repo.get_key_info.return_value = {
        "tg_id": 1,
        "is_active": True,
        "settings": "{",
        "uuid": "test-uuid",
        "panel_host": "host",
        "inbound_id": 1
    }
    mock_panel_service.delete_client.return_value = True
    success, msg = await vpn_service.cancel_subscription(1, 1)
    assert success is True
