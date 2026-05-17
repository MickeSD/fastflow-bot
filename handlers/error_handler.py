import structlog
from aiogram import Router
from aiogram.types import ErrorEvent

from core.exceptions import PanelOfflineError

router = Router()
logger = structlog.get_logger(__name__)


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Глобальный перехватчик всех исключений в хэндлерах aiogram"""
    exception = event.exception

    # Логируем ошибку в формате JSON с полным контекстом
    logger.error(
        "unhandled_exception",
        error_type=type(exception).__name__,
        error_msg=str(exception),
        update_id=event.update.update_id if event.update else None,
        exc_info=exception,
    )

    # Если мы можем ответить юзеру, отправляем извинения
    if event.update:
        msg_text = "⚠️ Произошла внутренняя ошибка сервера. Администратор уведомлен."

        # Если это известная нам сетевая ошибка панели
        if isinstance(exception, PanelOfflineError):
            msg_text = "⚠️ Удаленный сервер панели временно недоступен. Попробуй позже."

        try:
            if event.update.message:
                await event.update.message.answer(msg_text)
            elif event.update.callback_query and event.update.callback_query.message:
                # В aiogram callback_query.message может быть InaccessibleMessage, но answer() обычно работает
                await event.update.callback_query.message.answer(msg_text)  # type: ignore
        except Exception:
            pass

    return True  # Сообщаем aiogram, что ошибка отработана и падать не нужно
