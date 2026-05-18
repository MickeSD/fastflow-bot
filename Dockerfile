# === Этап 1: Сборка (Builder) ===
FROM python:3.11-slim as builder
RUN apt-get update && apt-get install -y gcc g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# === Этап 2: Production образ ===
FROM python:3.11-slim
WORKDIR /app

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Создаем безопасную группу и пользователя с UID 1000
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

# Копируем код и сразу назначаем безопасного владельца
COPY --chown=appuser:appgroup . .

# Заблаговременно создаем структуру пустых файлов под монтирование volume, выставляя права
RUN mkdir -p backups && touch vpn_database.db bot.log \
    && chown -R appuser:appgroup /app && chmod -R 755 /app

EXPOSE 8080

# ✅ Переключаемся на изолированного пользователя
USER appuser

CMD ["python", "main.py"]