import os

import aiohttp.web
import redis.asyncio as aioredis
import structlog
from prometheus_client import generate_latest

from core.config import settings
from core.di import Container

logger = structlog.get_logger(__name__)


def check_auth(request: aiohttp.web.Request) -> bool:
    """Проверяет токен авторизации для доступа к служебным эндпоинтам."""
    provided_token = request.headers.get("X-Metrics-Token") or request.query.get("token")
    return provided_token == settings.metrics_token


async def metrics_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Отдает метрики для Prometheus с защитой авторизации."""
    if not check_auth(request):
        return aiohttp.web.Response(text="Unauthorized", status=401)

    return aiohttp.web.Response(
        body=generate_latest(),
        content_type="text/plain",
        charset="utf-8"
    )


async def health_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Глубокий health-check, верифицирующий внутренние и внешние компоненты системы."""
    if not check_auth(request):
        return aiohttp.web.Response(text="Unauthorized", status=401)

    container = request.app["container"]
    checks = {}

    # 1. Проверяем SQLite БД
    try:
        db = await container.db().connect()
        await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        checks["database"] = "fail"

    # 2. Проверяем доступность Redis
    try:
        redis_host = os.getenv("REDIS_HOST", "flow-redis")
        r_client = await aioredis.from_url(f"redis://{redis_host}:6379", socket_timeout=2)
        await r_client.ping()
        await r_client.close()
        checks["redis"] = "ok"
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        checks["redis"] = "fail"

    # Выставляем общий статус системы
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return aiohttp.web.json_response(
        {"status": status, "checks": checks},
        status=200 if status == "ok" else 503
    )

async def start_observability_server(container: Container, port: int = 8080) -> aiohttp.web.AppRunner:
    """Запускает фоновый HTTP-сервер для метрик и health-чеков"""
    app = aiohttp.web.Application()
    app["container"] = container

    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health", health_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()

    bind_host = os.getenv("OBSERVABILITY_HOST", "127.0.0.1")
    site = aiohttp.web.TCPSite(runner, bind_host, port)
    await site.start()

    logger.info(f"Health & Metrics сервер запущен на порту {port} (/metrics, /health)")
    return runner
