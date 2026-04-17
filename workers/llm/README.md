# LLM-воркер (анонимизация ПДн)

HTTP-сервис: принимает расшифровку (как ответ STT: `text` + `segments` с таймкодами), вызывает OpenAI-совместимый чат API (LM Studio и т.п.) и возвращает сущности, замаскированный текст и сегменты с теми же `start`/`end`.

## Установка (Windows / Linux)

```bash
cd workers/llm
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Запуск (Windows)

Должен быть доступен бэкенд с `/v1/chat/completions` (по умолчанию LM Studio на `http://127.0.0.1:1234/v1`).

```powershell
$env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e4b"
$env:LM_HTTP_TIMEOUT_SEC = "600"
$env:LM_TEMPERATURE = "0.15"
$env:LM_MAX_TOKENS = "8192"
$env:WORKER_TOKEN = "your-token"
uvicorn main:app --host 0.0.0.0 --port 8081
```

Проверка:

- `GET http://127.0.0.1:8081/health` → `{"status":"ok","service":"llm_pii"}`
- `POST http://127.0.0.1:8081/v1/anonymize` — JSON: `text`, опционально `segments`, `language`; заголовок `Authorization: Bearer <WORKER_TOKEN>`, если задан `WORKER_TOKEN`

Ответ: `transcript_plain`, `transcript_redacted`, `llm_entities`, `redaction_report`, `segments` (текст в сегментах замаскирован), поле `model`.

На основном сервере: базовый URL этого воркера, например `http://<IP>:8081`.
