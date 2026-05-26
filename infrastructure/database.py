from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite
import structlog
from aiogram import Bot

from core.config import ENCRYPTION_KEY
from core.security import decrypt_data, encrypt_data

logger = structlog.get_logger(__name__)

class Database:
    """Менеджер соединений с базой данных (Infrastructure Layer)"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Открывает новое изолированное соединение для каждой задачи."""
        async with aiosqlite.connect(self.db_path, timeout=20.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            yield conn

    async def close(self) -> None:
        """Заглушка для обратной совместимости, соединения теперь закрываются сами."""
        pass

    async def backup(self, backup_db: aiosqlite.Connection) -> None:
        async with self.connect() as conn:
            await conn.backup(backup_db)

    async def init_db(self, bot: Bot | None = None) -> None:
        if not ENCRYPTION_KEY:
            raise RuntimeError("FATAL: Переменная ENCRYPTION_KEY не найдена в .env!")

        test_str = "fastflow_test"
        try:
            enc = encrypt_data(test_str)
            if decrypt_data(enc) != test_str:
                raise ValueError("Ошибка математики шифрования")
        except Exception as e:
            raise RuntimeError(f"FATAL: Неверный формат ENCRYPTION_KEY! Ошибка: {e}") from e

        async with self.connect() as conn:
            async with conn.execute("SELECT COUNT(id) FROM keys WHERE is_active = 1 AND uuid_hash IS NULL") as cursor:
                row = await cursor.fetchone()
                if row and row[0] > 0:
                    raise RuntimeError(f"🚨 ФАТАЛЬНО: Найдено {row[0]} активных ключей без uuid_hash! Сначала выполните fill_hashes.py")

        logger.info("Подключение к БД успешно проверено.")
