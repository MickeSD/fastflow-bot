# === Этап 1: Сборка (Builder) ===
FROM python:3.11-slim as builder

# Устанавливаем системные зависимости, необходимые для компиляции некоторых Python-пакетов
RUN apt-get update && apt-get install -y gcc g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем Poetry
RUN pip install --no-cache-dir poetry

# Копируем только файлы конфигурации зависимостей
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости системно (без виртуального окружения, так как сам Docker - это уже изоляция)
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# === Этап 2: Production образ ===
FROM python:3.11-slim

WORKDIR /app

# Устанавливаем часовой пояс для планировщика задач
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Копируем установленные библиотеки из первого этапа
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Копируем весь наш код
COPY . .

# Прокидываем порт для сервера метрик (Health Checks)
EXPOSE 8080

# Команда для запуска бота
CMD ["python", "main.py"]