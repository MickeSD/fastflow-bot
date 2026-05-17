# Runbook: Инструкции по устранению сбоев

## Сценарий 1: Панель 3x-ui недоступна
**Симптомы:**
- В логах спам ошибками `PanelOfflineError`.
- Метрика `panel_api_request_seconds` уходит в таймаут.

**Действия:**
1. Проверить доступность сервера панели по SSH (ping / ssh root@ip).
2. Перезапустить службу на сервере панели: `systemctl restart x-ui`.
3. Убедиться, что IP панели не заблокирован РКН.

## Сценарий 2: Бот циклично перезагружается в Docker
**Симптомы:**
- `docker-compose ps` показывает статус `Restarting`.

**Действия:**
1. Прочитать логи: `docker-compose logs flow-app`.
2. Если ошибка связана с БД (Alembic) — зайти в контейнер и проверить версию базы: `docker-compose run --rm flow-app python -m alembic current`.
3. Если ошибка `ENCRYPTION_KEY` — проверить файл `.env`.