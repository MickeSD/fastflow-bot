import asyncio
import logging
import re
from logging.handlers import RotatingFileHandler
from typing import Any, MutableMapping

import structlog

from core.config import BASE_DIR

SENSITIVE_KEYS = {"password", "pass", "token", "secret", "key", "settings", "id", "uuid", "email", "vless", "url"}

class AdminActionFilter(logging.Filter):
    """Фильтр, который пропускает только события аудита администратора"""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, dict) and "event" in record.msg:
            return "admin_" in str(record.msg["event"])
        # ✅ Ищем точное вхождение JSON-ключа, чтобы избежать false positives
        return '"event": "admin_' in str(record.msg)


def recursive_sanitize(data: Any, current_key: str = "") -> Any:
    """Рекурсивно обходит словари и списки, маскируя секреты."""
    if isinstance(data, dict):
        return {k: recursive_sanitize(v, str(k)) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return type(data)(recursive_sanitize(v, current_key) for v in data)
    elif isinstance(data, str):
        # Если название ключа намекает на секрет - скрываем полностью
        if current_key.lower() in SENSITIVE_KEYS:
            return "***-MASKED-***"

        clean_val = data.replace("\n", " ").replace("\r", " ")
        val = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "***-UUID-***", clean_val)
        val = re.sub(r"(vless://)[^@]+(@)", r"\1***\2", val)
        val = re.sub(r"user_\d+(_[0-9a-fA-Za-z]+)?", "user_***_masked", val)
        return val
    return data

def sensitive_data_processor(
    logger: Any, log_method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Маскирует персональные данные и предотвращает Log Injection (рекурсивно)"""
    for key, value in list(event_dict.items()):
        event_dict[key] = recursive_sanitize(value, key)
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
    """Глобальная настройка JSON-логирования с сепарацией логов админа"""
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)  # ✅ Гарантируем, что папка существует

    log_file = logs_dir / "bot.log"
    admin_log_file = logs_dir / "admin_actions.log"

    # Обработчик для ВСЕХ логов
    main_file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")

    # ✅ Специальный обработчик ТОЛЬКО для действий админа
    admin_file_handler = RotatingFileHandler(admin_log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    admin_file_handler.addFilter(AdminActionFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            main_file_handler,
            admin_file_handler, # Подключаем второй хэндлер
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
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
