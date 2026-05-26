import asyncio
import hmac
import os

import aiohttp.web
import redis.asyncio as aioredis
import structlog
from prometheus_client import generate_latest

from core.config import settings
from core.di import Container

logger = structlog.get_logger(__name__)


def check_auth(request: aiohttp.web.Request) -> bool:
    """Проверяет токен авторизации для доступа к служебным эндпоинтам с защитой от тайминг-атак."""
    # ✅ ИСПРАВЛЕНИЕ: Принимаем токен ТОЛЬКО через защищенный заголовок, никаких URL-параметров.
    provided_token = request.headers.get("X-Metrics-Token") or ""
    return hmac.compare_digest(provided_token.encode('utf-8'), settings.metrics_token.encode('utf-8'))


async def metrics_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Отдает метрики для Prometheus с защитой авторизации."""
    if not check_auth(request):
        await asyncio.sleep(0.1)
        return aiohttp.web.Response(text="Unauthorized", status=401)

    return aiohttp.web.Response(
        body=generate_latest(),
        content_type="text/plain",
        charset="utf-8"
    )


async def health_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    if not check_auth(request):
        await asyncio.sleep(0.1)
        return aiohttp.web.Response(text="Unauthorized", status=401)

    container = request.app["container"]
    checks = {}

    # 1. Проверяем SQLite БД с жестким таймаутом
    try:
        async with container.db().connect() as db:
            await asyncio.wait_for(db.execute("SELECT 1"), timeout=3.0)
        checks["database"] = "ok"
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        checks["database"] = "fail"

    # 2. Проверяем доступность Redis с жестким таймаутом
    try:
        redis_host = os.getenv("REDIS_HOST", "flow-redis")
        redis_password = os.getenv("REDIS_PASSWORD", "")
        redis_url = f"redis://:{redis_password}@{redis_host}:6379" if redis_password else f"redis://{redis_host}:6379"

        r_client = await aioredis.from_url(redis_url, socket_timeout=2)
        # ✅ Ограничиваем ожидание пинга
        await asyncio.wait_for(r_client.ping(), timeout=3.0)
        await r_client.close()
        checks["redis"] = "ok"
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        checks["redis"] = "fail"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return aiohttp.web.json_response({"status": status, "checks": checks}, status=200 if status == "ok" else 503)

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
