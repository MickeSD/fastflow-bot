import json

import structlog

from infrastructure.repositories import KeyRepository
from services.panel import (
    add_client_to_panel,
    delete_client_from_panel,
    inbound_exists,
    update_client_in_panel,
)

logger = structlog.get_logger(__name__)

class VpnService:
    def __init__(self, key_repo: KeyRepository) -> None:
        self.key_repo = key_repo

    async def extend_key(self, key_id: int, days: int) -> tuple[bool, str]:
        info = await self.key_repo.get_key_info(key_id)
        if not info:
            return False, "❌ Ключ не найден в базе."

        inbound_status = await inbound_exists(info["panel_host"], info["inbound_id"] or 1)

        if inbound_status is False:
            return False, f"❌ Ошибка: Входящее подключение (Inbound ID: {info['inbound_id']}) удалено на панели!\nПродление невозможно."
        elif inbound_status is None:
            logger.error("panel_offline", panel=info['panel_host'], msg="Панель не отвечает")
            return False, "❌ Ошибка: Сервер панели недоступен. Продление отменено в целях безопасности."

        if info["is_active"]:
            success = await update_client_in_panel(
                info["panel_host"], info["inbound_id"], info["uuid"], f"user_{info['tg_id']}", settings=info["settings"]
            )
        else:
            success = await add_client_to_panel(
                info["panel_host"], info["inbound_id"], info["uuid"], f"user_{info['tg_id']}", settings=info["settings"]
            )

        if success:
            await self.key_repo.extend_subscription(key_id, int(days))
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

        # 1. Удаляем с панели
        success = await delete_client_from_panel(
            key_info["panel_host"], key_info["inbound_id"] or 1, client_identifier
        )

        # 2. Выключаем в БД
        if success:
            await self.key_repo.deactivate_key(key_id)
            return True, "✅ Ты успешно отписался. Твой ключ отключен."

        return False, "❌ Ошибка сервера панели. Пожалуйста, попробуй позже."
