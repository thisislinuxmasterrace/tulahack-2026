# Gateway (Go)

Публичный HTTP API: приём аудио, загрузка в объектное хранилище, постановка задачи в очередь, выдача статусов и метаданных обработки.

## Сборка и запуск

```bash
go run ./cmd/gateway
# или
go build -o bin/gateway ./cmd/gateway && ./bin/gateway
```

Переменные окружения: `GATEWAY_ADDR` (по умолчанию `:8080`), `DATABASE_URL`, `REDIS_URL`, `S3_*`, `JWT_*` — см. корневой `.env.example`.
