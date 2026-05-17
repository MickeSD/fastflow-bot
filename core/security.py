import structlog
from cryptography.fernet import InvalidToken

from core.config import cipher
from core.exceptions import DecryptionError

logger = structlog.get_logger(__name__)

def encrypt_data(text: str) -> str:
    """Шифрует данные перед записью в БД"""
    if not cipher or not text:
        return text
    return cipher.encrypt(text.encode()).decode()

def decrypt_data(text: str) -> str:
    """Расшифровывает данные, полученные из БД"""
    if not cipher or not text:
        return text
    try:
        return cipher.decrypt(text.encode()).decode()
    except InvalidToken as e:
        logger.error(f"🚨 ФАТАЛЬНАЯ ОШИБКА: Неверный ключ шифрования для строки {text[:10]}...")
        raise DecryptionError("Неверный токен шифрования (возможно ключ был изменен)") from e
    except Exception as e:
        logger.warning(f"⚠️ Ошибка расшифровки: {e}")
        raise DecryptionError(f"Ошибка расшифровки: {e}") from e
