# === Этап 1: Сборка (Builder) ===
FROM python:3.11-slim@sha256:9a7765b36773a37061455b332f18e265e7f58f6fea9c419a550d2a8b0e9db834 as builder

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y gcc g++ && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# В Distroless нет команд mkdir и chown. 
# Поэтому мы создаем нужные папки здесь и выдаем права пользователю nonroot (его UID в Distroless всегда 65532)
RUN mkdir -p /app/db_data /app/backups /app/logs \
    && chown -R 65532:65532 /app

# === Этап 2: Production образ (Distroless / Zero Attack Surface) ===
# Используем официальный distroless образ от Google от лица пользователя nonroot
FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

# Настраиваем часовой пояс
ENV TZ=Europe/Moscow

# Устанавливаем путь к библиотекам, чтобы Python в Distroless их увидел
ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages

# Копируем установленные библиотеки из builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Копируем пустые папки (logs, db_data, backups) с правильными правами владельца 65532
COPY --from=builder --chown=nonroot:nonroot /app /app

# Копируем весь наш код
COPY --chown=nonroot:nonroot . .

EXPOSE 8080

# В Distroless нет bash, поэтому команды выполняются напрямую через бинарник Python
ENTRYPOINT ["python"]
CMD ["main.py"]