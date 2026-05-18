import asyncio

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile

logger = structlog.get_logger(__name__)

async def safe_send_message(bot: Bot, chat_id: int, text: str, max_retries: int = 3) -> bool:
    """
    Безопасно отправляет текстовое сообщение в Telegram.
    Автоматически обрабатывает лимиты (Throttling API) и блокировки бота.
    """
    for attempt in range(1, max_retries + 1):
        try:
            await bot.send_message(chat_id, text)
            return True
        except TelegramRetryAfter as e:
            logger.warning(f"⏳ Telegram API лимит! Ждем {e.retry_after} сек. Попытка {attempt}/{max_retries}...")
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            logger.warning(f"🚫 Бот заблокирован пользователем {chat_id}.")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Ошибка отправки {attempt}/{max_retries} в чат {chat_id}: {e}")
            if attempt == max_retries:
                return False
            await asyncio.sleep(1)
    return False

async def safe_send_document(bot: Bot, chat_id: int, document: FSInputFile, caption: str = "") -> None:
    """
    Безопасно отправляет файлы и документы администратору бота.
    Устойчив к сетевым прерываниям.
    """
    try:
        await bot.send_document(chat_id, document=document, caption=caption)
    except TelegramRetryAfter as e:
        logger.warning(f"⏳ Telegram API лимит (файлы)! Ждем {e.retry_after} сек...")
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_document(chat_id, document=document, caption=caption)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Не удалось отправить документ в {chat_id}: {e}")
