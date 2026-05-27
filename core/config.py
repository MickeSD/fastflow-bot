import os
import re
from pathlib import Path

from aiohttp import ClientTimeout
from cryptography.fernet import Fernet, MultiFernet
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# строгая схема валидации переменных окружения
class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_id: int = Field(0, alias="ADMIN_ID")
    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    payment_phone: str = Field("+7 (000) 000-00-00", alias="PAYMENT_PHONE")

    # ✅ Новые секреты без дефолтных значений
    metrics_token: str = Field(alias="METRICS_TOKEN")
    uuid_hash_secret: str = Field(alias="UUID_HASH_SECRET")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="allow"
    )

    @field_validator("metrics_token", "uuid_hash_secret")
    @classmethod
    def validate_lengths(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("🚨 Секреты (METRICS_TOKEN и UUID_HASH_SECRET) должны быть не короче 32 символов!")
        return v

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

class PanelConfig(BaseModel):
    """Строгая схема валидации для каждой панели"""
    url: str
    user: str
    pass_: str = Field(alias="pass")
    name: str

PANELS = {}
for key, value in os.environ.items():
    match = re.match(r"^PANEL_(\d+)_HOST$", key)
    if match:
        idx = match.group(1)
        host = value
        raw_url = (os.getenv(f"PANEL_{idx}_URL") or "").rstrip("/")
        raw_user = os.getenv(f"PANEL_{idx}_USER")
        raw_pas = os.getenv(f"PANEL_{idx}_PASS")
        raw_name = os.getenv(f"PANEL_{idx}_NAME", f"🌐 Сервер {host}")

        # Явные проверки помогают mypy понять, что значения больше не None
        if not host or not raw_url or not raw_user or not raw_pas:
            raise ValueError(f"🚨 ФАТАЛЬНАЯ ОШИБКА: Неполная конфигурация для панели PANEL_{idx} в .env")

        # Передаем словарь через model_validate, чтобы Pydantic сам разобрался с алиасом 'pass'
        validated = PanelConfig.model_validate({
            "url": raw_url,
            "user": raw_user,
            "pass": raw_pas,
            "name": raw_name
        })
        PANELS[host] = validated.model_dump(by_alias=True)
