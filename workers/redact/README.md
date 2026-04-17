# Redact-воркер (замена фрагментов на бип)

HTTP-сервис: принимает исходное аудио и JSON с интервалами (`redaction_report.spans` или `llm_entities` с `start_ms`/`end_ms`), накладывает бип на эти участки и отдаёт файл назад. Шлюз (Go) сам тянет файл из S3, вызывает этот сервис и загружает результат обратно в MinIO.

## Зависимости

Для **pydub** в системе нужен **ffmpeg** (декодирование входа и экспорт WAV).

## Установка (Windows / Linux)

```bash
cd workers/redact
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Запуск (Windows)

```powershell
$env:WORKER_TOKEN = "your-token"
$env:HOST = "0.0.0.0"
$env:PORT = "8082"
uvicorn main:app --host 0.0.0.0 --port 8082
```

Проверка:

- `GET http://127.0.0.1:8082/health` → `{"status":"ok","service":"audio_redact"}`
- `POST http://127.0.0.1:8082/v1/redact` — `multipart/form-data`:
  - поле **`file`** — аудиофайл (как у STT);
  - поле **`report`** — строка JSON: объект с полями `redaction_report` и/или `llm_entities` (как в БД после LLM);
  - опционально **`freq`** (Гц, по умолчанию 1000), **`gain_db`** (громкость бипа, по умолчанию −5);
  - заголовок `Authorization: Bearer <WORKER_TOKEN>`, если задан `WORKER_TOKEN`.

Ответ: тот же формат, что у входного файла (по расширению имени или `Content-Type` поля `file`): mp3, wav, ogg, webm, m4a, flac, aac, opus и т.д. Если тип не распознан — WAV. Соответствующий `Content-Type` в заголовке ответа.

На основном сервере (шлюз): `REDACT_BASE_URL=http://<IP>:8082` (тот же `WORKER_TOKEN`, что и у шлюза).
