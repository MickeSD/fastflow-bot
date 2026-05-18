import asyncio

import aiosqlite
import structlog
from aiogram import Bot

# ✅ Добавили импорт BASE_DIR сюда:
from core.config import ENCRYPTION_KEY
from core.security import decrypt_data, encrypt_data

logger = structlog.get_logger(__name__)

class Database:
    """Менеджер соединений с базой данных (Infrastructure Layer)"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> aiosqlite.Connection:
        """Получает или создает соединение с БД (Async-safe с защитой от Race Condition)."""
        async with self._lock:
            if self._conn is not None:
                try:
                    await self._conn.execute("SELECT 1")
                    return self._conn
                except Exception:
                    try:
                        await self._conn.close()
                    except Exception:
                        pass
                    self._conn = None

            # Создаем новое соединение строго внутри критической секции lock
            self._conn = await aiosqlite.connect(self.db_path, timeout=10.0)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            return self._conn

    async def close(self) -> None:
        """Безопасно закрывает соединение"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Соединение с БД закрыто.")

    async def backup(self, backup_db: aiosqlite.Connection) -> None:
        """Создает резервную копию базы данных"""
        conn = await self.connect()
        await conn.backup(backup_db)

    async def init_db(self, bot: Bot | None = None) -> None:
        """Инициализация БД (Миграции теперь управляются отдельно через Alembic)"""
        if not ENCRYPTION_KEY:
            logger.critical("FATAL: Переменная ENCRYPTION_KEY не найдена в .env!")
            exit(1)

        test_str = "fastflow_test"
        try:
            enc = encrypt_data(test_str)
            if decrypt_data(enc) != test_str:
                raise ValueError("Ошибка математики шифрования")
        except Exception as e:
            logger.critical(f"FATAL: Неверный формат ENCRYPTION_KEY! Ошибка: {e}")
            exit(1)

        logger.info("Подключение к БД успешно проверено.")
