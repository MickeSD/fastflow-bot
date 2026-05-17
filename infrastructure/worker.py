import os

import structlog
from aiogram import Bot
from arq import cron
from arq.connections import RedisSettings

from core.config import BOT_TOKEN
from core.di import Container
from core.logger import setup_logging
from services.scheduler import backup_database, check_payments, cleanup_inactive_keys

logger = structlog.get_logger(__name__)

async def startup(ctx: dict) -> None:
    """Выполняется при запуске воркера"""
    setup_logging()
    logger.info("Запуск Worker-а для фоновых задач (arq)...")

    container = Container()
    bot = Bot(token=BOT_TOKEN)

    # Сохраняем зависимости в контекст (ctx), который будет передаваться в каждую задачу
    ctx["container"] = container
    ctx["bot"] = bot

async def shutdown(ctx: dict) -> None:
    """Выполняется при остановке воркера"""
    logger.info("Остановка Worker-а...")
    await ctx["bot"].session.close()
    await ctx["container"].db().close()

class WorkerSettings:
    """Настройки очереди задач arq"""
    # В Docker-сети хост Redis совпадает с именем контейнера
    redis_settings = RedisSettings(host=os.getenv("REDIS_HOST", "flow-redis"), port=6379)

    on_startup = startup
    on_shutdown = shutdown

    # Сюда можно добавлять разовые асинхронные задачи
    functions = []

    # Наше расписание (Cron)
    cron_jobs = [
        cron(check_payments, hour=10, minute=0),
        cron(backup_database, hour=3, minute=0),
        cron(cleanup_inactive_keys, hour=4, minute=0),
    ]
