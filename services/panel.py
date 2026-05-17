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
    session = await PanelAPI.get_session()
    start_time = time.perf_counter() # ✅ Засекаем время начала
    parsed_url = urlparse(url)

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
                    return True

                msg = str(res.get("msg", "")).lower()
                if "delclient" in url.lower() and (
                    "not found" in msg or "no such" in msg
                ):
                    return True

                logger.warning("api_request_success_false", url=url, response=res)
                return False

            elif resp.status in [401, 403, 404]:
                logger.warning("auth_token_expired_or_missing", url=url, status=resp.status)

                # Идем логиниться и получать куки
                if await get_panel_session(session, panel):
                    # Бросаем ValueError, чтобы tenacity поймал его и сделал retry запроса (уже с куками)
                    raise ValueError("Auth token refreshed, retrying...")

                raise PanelAPIError(f"Авторизация отклонена или неверный URL (HTTP {resp.status})")
            else:
                raise PanelAPIError(f"Bad HTTP status: {resp.status}")

    except Exception as e:
        logger.warning("api_request_failed", url=url, error=str(e))
        if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
            raise PanelOfflineError(f"Сервер панели недоступен: {e}") from e
        raise PanelAPIError(f"Сбой API: {e}") from e

    finally:
        # ✅ Блок finally выполняется ВСЕГДА (даже если был return True или вылетела ошибка)
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
