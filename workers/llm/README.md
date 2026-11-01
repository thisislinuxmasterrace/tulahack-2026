# PII-воркер (анонимизация ПДн): GLiNER2 + Natasha + правила

HTTP-сервис для поиска ПДн на CPU. Принимает `text` и `segments` с таймкодами от STT,
возвращает `llm_entities`, `redaction_report` и текст с заменами.

## Как это работает

1. **GLiNER2** (`metrika-labs/ru-pii-ner-gliner2.5`, ~0.3B, Apache 2.0): телефоны, e-mail, локации, имена.
2. **Natasha** (Slovnet NER): локации и имена.
3. **Правила** (`detectors.py`): числа словами («сорок пять ноль восемь» -> 4508), классификация числовых
   последовательностей в passport/inn/snils/phone по ближайшему ключевому слову, длине и контрольным суммам,
   e-mail «собака/точка», сборка адреса из атомов (улица, дом, кв.).
4. Пересекающиеся спаны сливаются (приоритет: passport > snils > inn > email > phone > address > person), время берётся по
   словам Whisper.

Типы по умолчанию — `passport,inn,snils,phone,email,address`. Добавление `person` в `ENTITY_TYPES` включает имена.
Тип `person` не поддерживается интерфейсом: он отображается как «Телефон».

## Установка

```bash
cd workers/llm
python3.12 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

Модель скачается с Hugging Face при первом запросе (~1.1 ГБ); можно указать локальный путь в `GLINER_MODEL`.

## Запуск

```bash
export WORKER_TOKEN=your-token
uvicorn main:app --host 0.0.0.0 --port 8081
```

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `GLINER_MODEL` | `metrika-labs/ru-pii-ner-gliner2.5` | HF id или локальный путь |
| `GLINER_THRESHOLD` | `0.35` | порог (ниже — больше находок и ложных срабатываний) |
| `GLINER_CHUNK_CHARS` | `3000` | размер окна для длинных текстов (лимит модели — 4096 токенов) |
| `USE_NATASHA` | `1` | `0` отключает Natasha |
| `ENTITY_TYPES` | `passport,inn,snils,phone,email,address` | какие типы отдавать |
| `TORCH_THREADS` | авто | число потоков CPU |
| `WORKER_TOKEN` | — | Bearer-токен |
| `REDACTION_START_MS_PAD`, `REDACTION_END_MS_PAD` | `120`, `250` | запас по времени вокруг сущности |

Проверка: `GET /health`, `POST /v1/anonymize` (поля `text`, `segments`, `language`).

## Тесты на примерах

```bash
python tests/run_samples.py -v
```

В `tests/samples.json` — восемь синтетических диалогов с цифрами, числами и e-mail словами.
Скрипт выводит покрытие эталонных фрагментов, совпадения типов и ложные срабатывания.
Даты, полисы и карты из эталона не входят в поддерживаемые типы, но учитываются в общем счётчике покрытия.
