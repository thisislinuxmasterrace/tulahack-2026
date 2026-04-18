# Frontend · анонимизация голосовых данных

**Vue 3 + TypeScript + Vite**, **Vue Router**.

## Страницы

| Маршрут | Описание |
|---------|----------|
| `/` | Главная: сценарий и ссылка на загрузку |
| `/upload` | Загрузка аудио (нужна авторизация) |
| `/result/:uploadId` | Результат обработки с сервера |

## Запуск

```bash
npm install
npm run dev
```

В `vite.config.ts` для `npm run dev` запросы к `/api` проксируются на шлюз (по умолчанию `http://127.0.0.1:8080`; поменяйте `target`, если шлюз на другом порту).

## Продакшен (Docker + nginx)

Сборка статики и образ с nginx: см. [`Dockerfile`](Dockerfile) и [`nginx.conf`](nginx.conf). В compose сервис `web` слушает **8081** на хосте.

```bash
docker compose build web
# или из корня репозитория
docker compose up -d --build web
```

## Структура

- `src/layouts/AppShell.vue` — шапка и навигация
- `src/views/` — страницы
- `src/components/` — UI, транскрипт, аудио, отчёт, журнал обработки
- `src/types/result.ts` — типы для транскрипта и отчёта по маскировке
- `src/types/processingLog.ts` — тип записей `processing_events` из API
