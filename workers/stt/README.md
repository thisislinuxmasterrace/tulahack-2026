# STT-воркер (faster-whisper)

HTTP STT сервис для компьютера с GPU NVidia

## Установка (Windows / Linux)

```bash
cd workers/stt
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Запуск (Windows)

```powershell
$env:WHISPER_MODEL = "large-v3"
$env:WHISPER_DEVICE = "cuda"
$env:WHISPER_COMPUTE_TYPE = "float16"
$env:WHISPER_LANGUAGE = "ru"
$env:WHISPER_WORD_TIMESTAMPS = "true"
$env:WHISPER_MAX_PHRASE_SEC = "8"
$env:WHISPER_VAD_MIN_SILENCE_MS = "500"
$env:WORKER_TOKEN = "your-token"
uvicorn main:app --host 0.0.0.0 --port 8001
```

Ответ `segments`: у каждого элемента есть `start`/`end`/`text`; при включённых word-таймкодах — массив `words` (`word`, `start`, `end`). Длинные «фразы» Whisper режутся по словам, пока длительность куска не превышает `WHISPER_MAX_PHRASE_SEC`.

Проверка:

- `GET http://127.0.0.1:8001/health` → `{"status":"ok","service":"stt"}`
- `POST http://127.0.0.1:8001/v1/transcribe` — `multipart/form-data`, поле `file` = аудиофайл

На основном сервере: `STT_BASE_URL=http://<IP>:8001`.
