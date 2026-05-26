# === Этап 1: Сборка (Builder) ===
# УБРАЛИ @sha256, чтобы скачивалась свежая версия Debian с патчами безопасности!
FROM python:3.11-slim as builder

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y gcc g++ && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app

RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

RUN mkdir -p /app/db_data /app/backups /app/logs \
    && chown -R 65532:65532 /app

# === Этап 2: Production образ ===
FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

ENV TZ=Europe/Moscow
ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder --chown=nonroot:nonroot /app /app

# ✅ БЕЗОПАСНОСТЬ: Копируем ТОЛЬКО нужное для работы. Исключаем тесты, readme и мусор.
COPY --chown=nonroot:nonroot application/ ./application/
COPY --chown=nonroot:nonroot core/ ./core/
COPY --chown=nonroot:nonroot handlers/ ./handlers/
COPY --chown=nonroot:nonroot infrastructure/ ./infrastructure/
COPY --chown=nonroot:nonroot keyboards/ ./keyboards/
COPY --chown=nonroot:nonroot middlewares/ ./middlewares/
COPY --chown=nonroot:nonroot migrations/ ./migrations/
COPY --chown=nonroot:nonroot services/ ./services/
COPY --chown=nonroot:nonroot main.py alembic.ini ./

EXPOSE 8080
ENTRYPOINT ["python"]
CMD ["main.py"]