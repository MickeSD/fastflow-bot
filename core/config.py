import os
import re
from pathlib import Path

from aiohttp import ClientTimeout
from cryptography.fernet import Fernet, MultiFernet
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# строгая схема валидации переменных окружения
class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_id: int = Field(0, alias="ADMIN_ID")
    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    payment_phone: str = Field("+7 (000) 000-00-00", alias="PAYMENT_PHONE")
    metrics_token: str = Field("secure_default_token", alias="METRICS_TOKEN") # новый защитный токен

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="allow"  # Позволяет считывать динамические панели PANEL_1...
    )

    @field_validator("encryption_key")
    @classmethod
    def validate_fernet(cls, v: str) -> str:
        try:
            # Валидируем каждый ключ, если они переданы через запятую для ротации
            for key in v.split(","):
                if key.strip():
                    Fernet(key.strip().encode())
        except Exception as e:
            raise ValueError("🚨 Неверный формат ENCRYPTION_KEY для Fernet шифрования!") from e
        return v
# Инициализация автоматически проверит наличие и типы всех переменных
settings = Settings()  # type: ignore

BOT_TOKEN = settings.bot_token
ADMIN_ID = settings.admin_id
PAYMENT_PHONE = settings.payment_phone
ENCRYPTION_KEY = settings.encryption_key
# Создаем список Fernet-инстансов для поддержки старых и новых ключей
key_instances = [Fernet(k.strip().encode()) for k in ENCRYPTION_KEY.split(",") if k.strip()]
cipher = MultiFernet(key_instances)
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
