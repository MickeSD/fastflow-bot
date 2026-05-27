from dependency_injector import containers, providers

from application.services.vpn import VpnService
from core.config import BASE_DIR
from infrastructure.database import Database
from infrastructure.repositories import KeyRepository
from services.panel import PanelService


class Container(containers.DeclarativeContainer):
    """Главный контейнер зависимостей (DI Container)"""

    # Указываем, в каких модулях мы будем внедрять зависимости
    wiring_config = containers.WiringConfiguration(
        packages=["handlers", "services", "main"]
    )

    # 1. Провайдер базы данных (Singleton - существует в единственном экземпляре)
    db = providers.Singleton(
        Database,
        db_path=str(BASE_DIR / "db_data" / "vpn_database.db")
    )

    # 2. Провайдер репозитория (В него автоматически прокидывается db)
    key_repo = providers.Factory(
        KeyRepository,
        db=db
    )

    panel_service = providers.Factory(PanelService)

    vpn_service = providers.Factory(
        VpnService,
        key_repo=key_repo,
        panel_service=panel_service # Внедряем сервис панелей!
    )
