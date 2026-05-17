import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from core.config import BASE_DIR

# Читаем конфиг из alembic.ini
config = context.config

# Переопределяем URL базы данных, чтобы он всегда смотрел на наш файл
db_path = BASE_DIR / "vpn_database.db" # ✅ Внутри Docker он называется так!
config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    """Запуск миграций в online-режиме (асинхронно)."""
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    print("Offline mode is not supported with aiosqlite.")
else:
    run_migrations_online()
