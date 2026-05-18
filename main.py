import asyncio

import aiohttp.web
import structlog
from aiogram import Bot, Dispatcher
from alembic import command
from alembic.config import Config

from core.config import BOT_TOKEN
from core.di import Container
from core.logger import setup_logging
from core.observability import setup_observability
from handlers import admin, error_handler, user
from infrastructure.web import start_observability_server
from middlewares.throttling import ThrottlingMiddleware
from services.panel import PanelAPI

logger = structlog.get_logger(__name__)


# Обрати внимание: мы получаем container прямо в аргументах!
async def on_shutdown(bot: Bot, container: Container, web_runner: aiohttp.web.AppRunner) -> None:
    await web_runner.cleanup() # ✅ Глушим HTTP-сервер
    await container.db().close()
    await PanelAPI.close()
    await bot.session.close()
    logger.info("Соединения безопасно закрыты.")

def run_migrations() -> None:
    """Синхронный запуск миграций до старта асинхронного event loop."""
    logger.info("Запуск проверки миграций БД (Alembic)...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Схема БД актуальна!")

async def main() -> None:
    container = Container()
    bot = Bot(token=BOT_TOKEN)
    await container.db().init_db(bot)

    web_runner = await start_observability_server(container, port=8080)

    dp = Dispatcher()
    dp["container"] = container
    dp["web_runner"] = web_runner # ✅ Передаем runner в диспетчер
    dp.shutdown.register(on_shutdown)

    dp.message.middleware(ThrottlingMiddleware())

    # ✅ Подключаем роутер ошибок ПЕРВЫМ, чтобы он перехватывал всё
    dp.include_router(error_handler.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)

    logger.info("Бот запущен и планировщик активирован...")
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    # 1. Сначала настраиваем логирование и трейсы
    setup_logging()
    setup_observability()

    # 2. Выполняем миграции БД ВНЕ асинхронного цикла
    run_migrations()

    # 3. И только теперь безопасно запускаем самого бота
    asyncio.run(main())
