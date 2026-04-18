# Runner: оркестратор воркеров

Берёт задачи из Redis (очередь, куда кладёт gateway), гоняет пайплайн: MinIO -> STT -> LLM -> Redact -> MinIO -> PostgreSQL. HTTP к воркерам - по URL из env (машины с моделями работают отдельно, см. `workers/stt`, `workers/llm`, `workers/redact`).

## Установка (Windows / Linux)

```bash
cd backend/runner
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Запуск

Пока что удачи с этим 🫠, работаем над нормальным запуском в докере

Если всё-таки запускать отдельно, то нужны Redis, PostgreSQL, MinIO и три базовых URL воркеров.

Пример (PowerShell):

```powershell
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:DATABASE_URL = "postgres://postgres:postgres@127.0.0.1:5432/app?sslmode=disable"
$env:S3_ENDPOINT = "127.0.0.1:9000"
$env:S3_ACCESS_KEY = "minioadmin"
$env:S3_SECRET_KEY = "your-minio-secret"
$env:S3_BUCKET = "app"
$env:S3_USE_SSL = "false"
$env:S3_PUBLIC_BASE_URL = "http://127.0.0.1:9000"
$env:STT_BASE_URL = "http://127.0.0.1:8001"
$env:LLM_BASE_URL = "http://127.0.0.1:8002"
$env:REDACT_BASE_URL = "http://127.0.0.1:8082"
python main.py
```

`WORKER_TOKEN` — **тот же** секрет, что на сервисах `workers/stt`, `llm`, `redact` (`Authorization: Bearer …`). Если на воркере токен задан, а в runner — пустой, STT ответит **401**. В Docker задайте переменную в `.env` рядом с `docker-compose.yml`.

Таймауты (опционально): `STT_HTTP_TIMEOUT_SEC`, `LLM_HTTP_TIMEOUT_SEC`, `REDACT_HTTP_TIMEOUT_SEC` — по умолчанию 600 / 120 / 600 с.

## Docker

TODO