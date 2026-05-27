import json

import structlog

from infrastructure.repositories import KeyRepository
from services.panel import PanelService

logger = structlog.get_logger(__name__)

class VpnService:
    def __init__(self, key_repo: KeyRepository, panel_service: PanelService) -> None:
        self.key_repo = key_repo
        self.panel_service = panel_service

    async def extend_key(self, key_id: int, days: int) -> tuple[bool, str]:
        info = await self.key_repo.get_key_info(key_id)
        if not info:
            return False, "❌ Ключ не найден в базе."

        inbound_status = await self.panel_service.inbound_exists(info["panel_host"], info["inbound_id"] or 1)
        if inbound_status is False:
            return False, "❌ Ошибка: Входящее подключение удалено на панели!"
        elif inbound_status is None:
            logger.error("panel_offline", panel=info['panel_host'], msg="Панель не отвечает")
            return False, "❌ Сервер панели недоступен. Продление отменено."

        # Гарантируем, что ключ будет Включен (enable: True)
        try:
            settings_dict = json.loads(info["settings"]) if info["settings"] else {}
        except ValueError:
            return False, "❌ Ошибка: Поврежденные настройки ключа в базе данных."

        settings_dict["enable"] = True
        active_settings = json.dumps(settings_dict)
        email = settings_dict.get("email", f"user_{info['tg_id']}")

        if info["is_active"]:
            success = await self.panel_service.update_client(
                info["panel_host"], info["inbound_id"], info["uuid"], email, settings=active_settings
            )
        else:
            success = await self.panel_service.add_client(
                info["panel_host"], info["inbound_id"], info["uuid"], email, settings=active_settings
            )

        if success:
            # Передаем active_settings в БД
            await self.key_repo.extend_subscription(key_id, int(days), active_settings)
            return True, "✅ Подписка успешно продлена и активирована на сервере!"

        return False, "❌ Ошибка API панели. Продление отменено."

    async def cancel_subscription(self, key_id: int, tg_id: int) -> tuple[bool, str]:
        key_info = await self.key_repo.get_key_info(key_id)

        # Проверка владельца (Security)
        if not key_info or key_info["tg_id"] != tg_id:
            return False, "❌ В доступе отказано. Это не твой ключ!"

        if not key_info.get("is_active"):
            return False, "❌ Этот ключ уже деактивирован или удален."

        # Разбираем JSON
        try:
            settings_dict = json.loads(key_info["settings"]) if key_info["settings"] else {}
        except ValueError:
            settings_dict = {}

        if "password" in settings_dict and "id" not in settings_dict:
            client_identifier = settings_dict.get("email", f"user_{tg_id}")
        else:
            client_identifier = key_info["uuid"]

        # 1. Удаляем с панели (через изолированный сервис)
        success = await self.panel_service.delete_client(
            key_info["panel_host"], key_info["inbound_id"] or 1, client_identifier
        )

        # 2. Выключаем в БД
        if success:
            await self.key_repo.deactivate_key(key_id)
            return True, "✅ Ты успешно отписался. Твой ключ отключен."

        return False, "❌ Ошибка сервера панели. Пожалуйста, попробуй позже."

    async def suspend_subscription(self, key_id: int) -> bool:
        """Приостанавливает ключ на панели (Grace Period), но не удаляет его."""
        info = await self.key_repo.get_key_info(key_id)
        if not info:
            return False

        try:
            settings_dict = json.loads(info["settings"]) if info["settings"] else {}
        except ValueError:
            settings_dict = {}

        # Жестко отключаем ключ на уровне 3x-ui
        settings_dict["enable"] = False
        new_settings = json.dumps(settings_dict)

        email = settings_dict.get("email", f"user_{info['tg_id']}")

        # Отправляем обновленный конфиг на сервер
        success = await self.panel_service.update_client(
            info["panel_host"], info["inbound_id"] or 1, info["uuid"], email, settings=new_settings
        )

        if success:
            await self.key_repo.set_suspended_status(key_id, True, new_settings)
            return True
        return False
