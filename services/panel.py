import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import PANELS, REQUEST_TIMEOUT
from core.exceptions import PanelAPIError, PanelOfflineError
from core.observability import API_REQUEST_DURATION

logger = structlog.get_logger(__name__)

class PanelCircuitBreaker:
    """In-memory предохранитель для предотвращения перегрузки упавших узлов 3x-ui."""
    def __init__(self, fail_max: int = 5, reset_timeout: int = 60):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.state: dict[str, dict[str, Any]] = {}  # host -> {"failures": int, "tripped_at": float}

    def check(self, host: str) -> None:
        if host not in self.state:
            return
        data = self.state[host]
        if data["failures"] >= self.fail_max:
            if time.time() - data["tripped_at"] < self.reset_timeout:
                raise PanelOfflineError(f"🚨 Circuit Breaker активен для {host}. Узел временно заблокирован.")
            else:
                self.state[host] = {"failures": 0, "tripped_at": 0.0}

    def record_success(self, host: str) -> None:
        self.state[host] = {"failures": 0, "tripped_at": 0.0}

    def record_failure(self, host: str) -> None:
        if host not in self.state:
            self.state[host] = {"failures": 0, "tripped_at": 0.0}
        self.state[host]["failures"] += 1
        if self.state[host]["failures"] >= self.fail_max:
            self.state[host]["tripped_at"] = time.time()

panel_breaker = PanelCircuitBreaker()

class PanelAPI:
    """Одиночка (Singleton) для удержания пула соединений и куки авторизации"""

    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
        return cls._session

    @classmethod
    async def close(cls) -> None:
        if cls._session and not cls._session.closed:
            await cls._session.close()


async def get_panel_session(session: aiohttp.ClientSession, panel: dict[str, Any]) -> bool:
    login_data = {"username": panel["user"], "password": panel["pass"]}
    login_url = f"{panel['url']}/login"

    try:
        async with session.post(
            login_url, data=login_data, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status == 200:
                res = await resp.json()
                if res.get("success", False):
                    session.cookie_jar.update_cookies(resp.cookies)
                    logger.info("auth_success", url=login_url)
                    return True
                # Если 200 OK, но логин/пароль не подошли
                logger.error("auth_failed_bad_credentials", url=login_url, response=res)
                return False

            # Если URL неправильный (например, 404)
            logger.error("auth_failed_bad_status", url=login_url, status=resp.status)
            return False

    except Exception as e:
        logger.error("auth_failed_network_error", url=login_url, error=str(e))
        return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _safe_api_request(
    panel: dict[str, Any], url: str, payload: dict[str, Any] | None = None, method: str = "POST"
) -> bool:
    parsed_url = urlparse(url)
    host = parsed_url.hostname or "unknown"

    # 1. Проверяем состояние предохранителя для данного хоста
    panel_breaker.check(host)

    session = await PanelAPI.get_session()
    start_time = time.perf_counter()

    try:
        if method == "POST":
            req = session.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        elif method == "DELETE":
            req = session.delete(url, data=payload, timeout=REQUEST_TIMEOUT)
        else:
            req = session.get(url, timeout=REQUEST_TIMEOUT)

        async with req as resp:
            if resp.status == 200:
                res = await resp.json()
                if res.get("success", False):
                    panel_breaker.record_success(host)  # Сброс счетчика при успехе
                    return True

                msg = str(res.get("msg", "")).lower()
                if "delclient" in url.lower() and ("not found" in msg or "no such" in msg):
                    panel_breaker.record_success(host)
                    return True

                logger.warning("api_request_success_false", url=url, response=res)
                return False

            if resp.status == 401:
                logger.warning("api_request_401_unauthorized", url=url)
                # Пытаемся автоматически обновить сессию кук
                auth_success = await get_panel_session(session, panel)
                if auth_success:
                    # Выбрасываем ошибку, чтобы декоратор @retry перезапустил этот же метод
                    raise PanelAPIError("Сессия 3x-ui была обновлена, повторяем запрос...")
                else:
                    raise PanelAPIError("Критическая ошибка авторизации на панели 3x-ui")

            logger.error("api_request_bad_status", url=url, status=resp.status)
            return False

    except Exception as e:
        # Если это наш внутренний контролируемый ретрай для 401, не считаем его за сбой узла
        if isinstance(e, PanelAPIError) and "Сессия 3x-ui была обновлена" in str(e):
            pass
        else:
            panel_breaker.record_failure(host) # Фиксируем сбой предохранителем

        logger.warning("api_request_failed", url=url, error=str(e))
        if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
            raise PanelOfflineError(f"Сервер панели недоступен: {e}") from e
        if isinstance(e, PanelAPIError):
            raise e
        raise PanelAPIError(f"Сбой API: {e}") from e
    finally:
        # Блок finally выполняется всегда (даже если был return True или вылетела ошибка)
        # Поэтому мы гарантированно запишем время выполнения запроса
        duration = time.perf_counter() - start_time
        API_REQUEST_DURATION.labels(
            panel_host=parsed_url.hostname,
            method=method
        ).observe(duration)

async def add_client_to_panel(panel_host: str, inbound_id: int, client_uuid: str, email: str, settings: str | None = None) -> bool:
    panel = PANELS.get(panel_host)
    if not panel:
        return False
    client_data = (
        json.loads(settings)
        if settings
        else {
            "id": client_uuid,
            "alterId": 0,
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
        }
    )
    add_url = f"{panel['url']}/panel/api/inbounds/addClient"
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client_data]})}
    try:
        return await _safe_api_request(panel, add_url, payload)
    except Exception as e:
        logger.error(f"❌ Сервер {panel_host} недоступен для добавления клиента: {e}")
        return False


async def update_client_in_panel(
    panel_host: str, inbound_id: int, client_uuid: str, email: str, settings: str | None = None
) -> bool:
    panel = PANELS.get(panel_host)
    if not panel:
        return False
    client_data = (
        json.loads(settings)
        if settings
        else {
            "id": client_uuid,
            "alterId": 0,
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
        }
    )
    # Панель 3x-ui требует email в качестве identifier для протокола Hysteria2 (наличие password),
    # но использует client_uuid в качестве identifier для протокола VLESS.
    identifier = email if "password" in client_data else client_uuid
    update_url = f"{panel['url']}/panel/api/inbounds/updateClient/{identifier}"
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client_data]})}
    try:
        return await _safe_api_request(panel, update_url, payload)
    except Exception as e:
        logger.error(f"❌ Сервер {panel_host} недоступен для обновления клиента: {e}")
        return False


async def delete_client_from_panel(
    panel_host: str, inbound_id: int, client_identifier: str
) -> bool:
    panel = PANELS.get(panel_host)
    if not panel:
        return False

    del_url = (
        f"{panel['url']}/panel/api/inbounds/{inbound_id}/delClient/{client_identifier}"
    )
    payload = {
        "id": inbound_id,
        "settings": json.dumps(
            {"clients": [{"email": client_identifier, "id": client_identifier}]}
        ),
    }

    # Сначала пробуем POST, если панель вернула 405 Method Not Allowed - пробуем DELETE
    try:
        return await _safe_api_request(panel, del_url, payload, method="POST")
    except Exception:
        try:
            return await _safe_api_request(panel, del_url, payload, method="DELETE")
        except Exception as e:
            logger.error(f"❌ Сервер {panel_host} недоступен для удаления клиента: {e}")
            return False

async def inbound_exists(panel_host: str, inbound_id: int) -> bool | None:
    """Проверяет существование подключения (inbound) на панели.
    Возвращает:
        True - если подключение существует.
        False - если подключение не найдено (404/success: false).
        None - если произошел сетевой сбой (сервер оффлайн).
    """
    panel = PANELS.get(panel_host)
    if not panel:
        return False

    url = f"{panel['url']}/panel/api/inbounds/get/{inbound_id}"
    try:
        return await _safe_api_request(panel, url, method="GET")
    except Exception as e:
        logger.error(f"❌ Сервер {panel_host} недоступен для проверки inbound {inbound_id}: {e}")
        return None
