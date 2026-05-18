import asyncio
import logging
import re
from logging.handlers import RotatingFileHandler
from typing import Any, MutableMapping

import structlog

from core.config import BASE_DIR


def sensitive_data_processor(
    logger: Any, log_method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Маскирует UUID, токены, ссылки vless и технические email клиентов в логах"""
    for key, value in event_dict.items():
        if isinstance(value, str):
            val = re.sub(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "***-UUID-***",
                value,
            )
            val = re.sub(r"(vless://)[^@]+(@)", r"\1***\2", val)
            # зачищаем технические email панелей (например, user_526485744_abcde)
            val = re.sub(r"user_\d+(_[0-9a-fA-Za-z]+)?", "user_***_masked", val)
            event_dict[key] = val
    return event_dict


def asyncio_context_processor(
    logger: Any, log_method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Добавляет Task ID для отладки асинхронных задач"""
    try:
        task = asyncio.current_task()
        event_dict["task_id"] = task.get_name() if task else "Main"
    except RuntimeError:
        event_dict["task_id"] = "NoTask"
    return event_dict

def setup_logging() -> None:
    """Глобальная настройка JSON-логирования"""
    log_file = BASE_DIR / "bot.log"

    # Базовый конфиг перехватывает ВСЕ логи от других библиотек (aiogram, aiosqlite)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            asyncio_context_processor,
            sensitive_data_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False), # ✅ Формат JSON
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
