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

## Сравнение STT на CPU

Из корня проекта, с Python 3.12 и `ffmpeg`:

```bash
uv venv --python 3.12 .venv-stt-eval
uv pip install --python .venv-stt-eval/bin/python -r scripts/stt_eval_requirements.txt
.venv-stt-eval/bin/python scripts/stt_cpu_eval.py prepare
.venv-stt-eval/bin/python scripts/stt_cpu_eval.py calls
.venv-stt-eval/bin/python scripts/stt_cpu_eval.py run --engine gigaam --name gigaam
.venv-stt-eval/bin/python scripts/stt_cpu_eval.py run --engine whisper --beam 5 --batch 8 --name whisper
.venv-stt-eval/bin/python scripts/stt_cpu_report.py .stt-eval/results/gigaam.json .stt-eval/results/whisper.json --plot
```

Стенд скачивает аудио и модели в `.stt-eval/`, считает время, пиковый RSS и WER по группам записей.
Для разговоров без эталонной расшифровки WER не вычисляется. Время загрузки моделей не входит в замеры.
Сводка сохраняется в `.stt-eval/summary.json`, график — в `.stt-eval/stt-cpu-comparison.png`.
