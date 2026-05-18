from unittest.mock import AsyncMock, patch

import pytest

from application.services.vpn import VpnService


@pytest.fixture
def mock_key_repo() -> AsyncMock:
    return AsyncMock()

@pytest.fixture
def vpn_service(mock_key_repo: AsyncMock) -> VpnService:
    return VpnService(key_repo=mock_key_repo)

@pytest.mark.asyncio
async def test_extend_key_not_found(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Продление несуществующего ключа"""
    mock_key_repo.get_key_info.return_value = None
    success, msg = await vpn_service.extend_key(1, 30)
    assert success is False
    assert "не найден" in msg

@pytest.mark.asyncio
@patch("application.services.vpn.inbound_exists")
async def test_extend_key_inbound_missing(mock_inbound_exists: AsyncMock, vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Ошибка продления, если Inbound удален на панели"""
    mock_key_repo.get_key_info.return_value = {
        "panel_host": "test_host", "inbound_id": 1, "is_active": True
    }
    mock_inbound_exists.return_value = False

    success, msg = await vpn_service.extend_key(1, 30)
    assert success is False
    assert "удалено на панели" in msg

@pytest.mark.asyncio
@patch("application.services.vpn.inbound_exists", return_value=True)
@patch("application.services.vpn.update_client_in_panel", return_value=True)
async def test_extend_key_success(mock_update: AsyncMock, mock_inbound: AsyncMock, vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Успешное продление активного ключа"""
    mock_key_repo.get_key_info.return_value = {
        "panel_host": "host", "inbound_id": 1, "is_active": True,
        "uuid": "uuid123", "tg_id": 999, "settings": "{}"
    }

    success, msg = await vpn_service.extend_key(1, 30)
    assert success is True
    assert "успешно продлена" in msg
    mock_key_repo.extend_subscription.assert_called_once_with(1, 30)

@pytest.mark.asyncio
async def test_cancel_subscription_wrong_user(vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Отмена чужой подписки (Security Guard)"""
    mock_key_repo.get_key_info.return_value = {"tg_id": 111}
    success, msg = await vpn_service.cancel_subscription(1, 999) # Попытка удалить чужой
    assert success is False
    assert "Это не твой ключ" in msg

@pytest.mark.asyncio
@patch("application.services.vpn.delete_client_from_panel", return_value=True)
async def test_cancel_subscription_success(mock_delete: AsyncMock, vpn_service: VpnService, mock_key_repo: AsyncMock) -> None:
    """Тест: Успешная отмена подписки"""
    mock_key_repo.get_key_info.return_value = {
        "tg_id": 999, "is_active": True, "settings": '{"email": "test@test"}',
        "uuid": "uuid", "panel_host": "host", "inbound_id": 1
    }
    success, msg = await vpn_service.cancel_subscription(1, 999)
    assert success is True
    mock_key_repo.deactivate_key.assert_called_once_with(1)
