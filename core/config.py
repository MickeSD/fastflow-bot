import os
import re
from pathlib import Path

from aiohttp import ClientTimeout
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# ✅ Строгая схема валидации переменных окружения
class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_id: int = Field(0, alias="ADMIN_ID")
    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    payment_phone: str = Field("+7 (000) 000-00-00", alias="PAYMENT_PHONE")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="allow"  # Позволяет считывать динамические панели PANEL_1...
    )

    @field_validator("encryption_key")
    @classmethod
    def validate_fernet(cls, v: str) -> str:
        try:
            Fernet(v.encode())
        except Exception as e:
            raise ValueError("🚨 Неверный формат ENCRYPTION_KEY для Fernet шифрования!") from e
        return v

# Инициализация автоматически проверит наличие и типы всех переменных
settings = Settings()  # type: ignore

BOT_TOKEN = settings.bot_token
ADMIN_ID = settings.admin_id
PAYMENT_PHONE = settings.payment_phone
ENCRYPTION_KEY = settings.encryption_key
cipher = Fernet(ENCRYPTION_KEY.encode())
REQUEST_TIMEOUT = ClientTimeout(total=10)

PANELS = {}
for key, value in os.environ.items():
    match = re.match(r"^PANEL_(\d+)_HOST$", key)
    if match:
        idx = match.group(1)
        host = value
        url = (os.getenv(f"PANEL_{idx}_URL") or "").rstrip("/")
        user = os.getenv(f"PANEL_{idx}_USER")
        pas = os.getenv(f"PANEL_{idx}_PASS")
        name = os.getenv(f"PANEL_{idx}_NAME", f"🌐 Сервер {host}")

        # ✅ Жесткая проверка: если конфигурация панели неполная — падаем до старта
        if not all([host, url, user, pas]):
            raise ValueError(f"🚨 ФАТАЛЬНАЯ ОШИБКА: Неполная конфигурация для панели PANEL_{idx} в .env")

        PANELS[host] = {
            "url": url,
            "user": user,
            "pass": pas,
            "name": name,
        }
