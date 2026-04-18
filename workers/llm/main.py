from __future__ import annotations

import json
import math
import os
import re
from typing import Annotated, Any, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="LLM PII Worker", version="0.1.0")

ENTITY_TYPES = frozenset(
    {
        "passport",
        "inn",
        "snils",
        "phone",
        "email",
        "address",
    }
)


def _token_ok(authorization: str | None) -> bool:
    expected = (os.getenv("WORKER_TOKEN") or "").strip()
    if not expected:
        return True
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return authorization.removeprefix("Bearer ").strip() == expected


def require_auth(authorization: Annotated[Optional[str], Header()] = None) -> None:
    if not _token_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")


class WordTS(BaseModel):
    word: str
    start: float
    end: float
    probability: Optional[float] = None


class SegmentIn(BaseModel):
    start: float
    end: float
    text: str = ""
    words: Optional[list[WordTS]] = None


class AnonymizeRequest(BaseModel):
    """Формат как у ответа STT: поля text и segments с таймкодами."""

    text: str = ""
    segments: Optional[list[SegmentIn]] = None
    language: Optional[str] = None


def _full_text_from_segments(segments: list[SegmentIn]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def _segment_char_ranges(segments: list[SegmentIn]) -> list[tuple[int, int, float, float]]:
    """По каждому сегменту: интервал символов [start, end) во всём тексте и границы времени в секундах."""
    ranges: list[tuple[int, int, float, float]] = []
    pos = 0
    for i, s in enumerate(segments):
        t = s.text.strip()
        if not t:
            continue
        if i > 0 and ranges:
            pos += 1
        start_c = pos
        pos += len(t)
        ranges.append((start_c, pos, float(s.start), float(s.end)))
    return ranges


def _segment_char_ranges_with_ref(segments: list[SegmentIn]) -> list[tuple[int, int, SegmentIn]]:
    """Как _segment_char_ranges, но с объектом сегмента для привязки слов."""
    ranges: list[tuple[int, int, SegmentIn]] = []
    pos = 0
    for i, s in enumerate(segments):
        t = s.text.strip()
        if not t:
            continue
        if i > 0 and ranges:
            pos += 1
        start_c = pos
        pos += len(t)
        ranges.append((start_c, pos, s))
    return ranges


def _word_local_char_ranges(seg: SegmentIn) -> list[tuple[int, int, float, float]] | None:
    """Позиции слов в локальных координатах seg.text.strip(); None если слова не совпали с текстом."""
    seg_text = seg.text.strip()
    if not seg_text or not seg.words:
        return None
    ranges: list[tuple[int, int, float, float]] = []
    pos = 0
    for w in seg.words:
        tok = (w.word or "").strip()
        if not tok:
            continue
        idx = seg_text.find(tok, pos)
        if idx < 0:
            return None
        if idx > pos:
            gap = seg_text[pos:idx]
            if gap.strip():
                return None
        ws, we = idx, idx + len(tok)
        ranges.append((ws, we, float(w.start), float(w.end)))
        pos = we
    while pos < len(seg_text) and seg_text[pos].isspace():
        pos += 1
    if pos != len(seg_text):
        return None
    return ranges


def _local_span_to_times_in_segment(seg: SegmentIn, la: int, lb: int) -> tuple[float, float]:
    """Интервал времени для [la, lb) в координатах seg.text.strip()."""
    seg_text = seg.text.strip()
    if not seg_text:
        return float(seg.start), float(seg.end)
    la = max(0, min(la, len(seg_text)))
    lb = max(0, min(lb, len(seg_text)))
    if lb <= la:
        return float(seg.start), float(seg.end)
    wr = _word_local_char_ranges(seg)
    if wr:
        t0: float | None = None
        t1: float | None = None
        for ws, we, st, en in wr:
            if we <= la or ws >= lb:
                continue
            if t0 is None:
                t0, t1 = st, en
            else:
                t0 = min(t0, st)
                t1 = max(t1, en)
        if t0 is not None and t1 is not None:
            return t0, t1
    seg_len = len(seg_text)
    seg_dur = float(seg.end) - float(seg.start)
    if seg_len <= 0 or seg_dur <= 0:
        return float(seg.start), float(seg.end)
    st = float(seg.start) + (la / seg_len) * seg_dur
    en = float(seg.start) + (lb / seg_len) * seg_dur
    return st, en


def _redaction_end_pad_sec() -> float:
    """Запас на конце интервала: Whisper часто заканчивает слово раньше реального затухания в аудио."""
    try:
        ms = int(os.getenv("REDACTION_END_MS_PAD", "250"))
    except ValueError:
        ms = 250
    return max(0, ms) / 1000.0


def _redaction_start_pad_sec() -> float:
    """Запас перед началом: начало цифр/слов в аудио часто раньше границы по символам при пропорции или VAD."""
    try:
        ms = int(os.getenv("REDACTION_START_MS_PAD", "120"))
    except ValueError:
        ms = 120
    return max(0, ms) / 1000.0


def _ms_from_sec_start(t: float) -> int:
    return max(0, int(math.floor(t * 1000 + 1e-9)))


def _ms_from_sec_end(t: float) -> int:
    # int(t*1000) режет хвост (напр. 8.88*1000 → 8879); для конца цензуры нужен ceil
    return max(0, int(math.ceil(t * 1000 - 1e-9)))


def _char_span_to_time(segments: list[SegmentIn], full_text: str, cs: int, ce: int) -> tuple[float, float]:
    """Время по пересечению span с сегментами; внутри сегмента — по словам Whisper, иначе пропорционально."""
    if not segments or ce <= cs:
        return 0.0, 0.0
    pairs = _segment_char_ranges_with_ref(segments)
    if not pairs:
        return 0.0, 0.0
    t0: float | None = None
    t1: float | None = None
    for g_s, g_e, seg in pairs:
        if g_e <= cs or g_s >= ce:
            continue
        overlap_left = max(cs, g_s)
        overlap_right = min(ce, g_e)
        la = overlap_left - g_s
        lb = overlap_right - g_s
        st, en = _local_span_to_times_in_segment(seg, la, lb)
        if t0 is None:
            t0, t1 = st, en
        else:
            t0 = min(t0, st)
            t1 = max(t1, en)
    if t0 is None or t1 is None:
        return 0.0, 0.0
    t0 = max(0.0, t0 - _redaction_start_pad_sec())
    t1 = t1 + _redaction_end_pad_sec()
    return t0, t1


def _apply_redactions(text: str, entities: list[dict[str, Any]]) -> str:
    """Подстановка replacement с конца строки, чтобы не сбить индексы при нескольких заменах."""
    spans: list[tuple[int, int, str]] = []
    for e in entities:
        orig = e.get("original")
        rep = e.get("replacement") or "[REDACTED]"
        if not isinstance(orig, str) or not orig:
            continue
        start = e.get("start_char")
        end = e.get("end_char")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
            spans.append((start, end, str(rep)))
            continue
        idx = text.find(orig)
        if idx >= 0:
            spans.append((idx, idx + len(orig), str(rep)))
    spans.sort(key=lambda x: x[0], reverse=True)
    out = text
    for a, b, rep in spans:
        out = out[:a] + rep + out[b:]
    return out


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    dec = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(raw, i)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object in model output")


# Упрощённый сценарий: весь текст в промпте; в проде нужны лимиты и защита от prompt injection.
def _build_llm_messages(user_text: str, language: str | None) -> list[dict[str, str]]:
    lang = language or "ru"
    system = (
        "Ты — строгий AI-ассистент для поиска персональных данных (NER). "
        "Отвечай только валидным JSON без пояснений до или после."
    )
    user = f"""Язык текста: {lang}.

Текст расшифровки:
\"\"\"{user_text}\"\"\"

Найди все фрагменты по категориям.
Используй СТРОГО следующие значения для поля replacement:
- passport — серия и номер паспорта -> [ПАСПОРТ]
- inn — ИНН (10 или 12 цифр) -> [ИНН]
- snils — СНИЛС -> [СНИЛС]
- phone — телефон (в т.ч. «+7», группы цифр) -> [ТЕЛЕФОН]
- email — email -> [EMAIL]
- address — адрес (улица, дом, квартира и т.п.) -> [АДРЕС]

Правила:
1. original должен ДОСЛОВНО совпадать с подстрокой текста (копипаст). Сохраняй ВСЕ лишние пробелы, дефисы и опечатки ровно так, как они идут в тексте. НЕ исправляй ошибки распознавания (например, если в тексте криво «78 -32-33», верни именно «78 -32-33»).
2. original должен быть максимально коротким: только сами данные (без «добрый день», «мой номер» и т.п.).
3. passport: только серия/номер, не целое предложение; inn/phone — по возможности только цифры и знаки номера; для телефона сохраняй «+»/«плюс» только если так в тексте.
4. Не дублируй одно и то же; не выдумывай; при сомнении не включай.
5. Если персональных данных в тексте НЕТ, верни пустой массив: {{"entities": []}}.

Формат ответа (строго один объект JSON, без полного переписывания текста — только список сущностей):
{{
  "entities": [
    {{
      "entity_type": "phone",
      "original": "+7 999 123-45-67",
      "replacement": "[ТЕЛЕФОН]"
    }},
    {{
      "entity_type": "passport",
      "original": "988 032",
      "replacement": "[ПАСПОРТ]"
    }}
  ]
}}"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _call_lm_studio(messages: list[dict[str, str]]) -> str:
    base = (os.getenv("LM_STUDIO_BASE_URL") or "http://127.0.0.1:1234/v1").rstrip("/")
    model = (os.getenv("LM_MODEL") or "").strip()
    if not model:
        model = "google/gemma-4-e4b"
    url = f"{base}/chat/completions"
    timeout = float(os.getenv("LM_HTTP_TIMEOUT_SEC", "600"))
    temp = float(os.getenv("LM_TEMPERATURE", "0.15"))
    max_tokens = int(os.getenv("LM_MAX_TOKENS", "8192"))

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"LM Studio HTTP {r.status_code}: {r.text[:2000]}",
            )
        data = r.json()

    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="empty model response")
    return content


def _normalize_entities(
    raw_entities: list[Any],
    full_text: str,
    segments: list[SegmentIn],
) -> list[dict[str, Any]]:
    """Нормализует entities из JSON модели: границы в тексте и интервалы времени по сегментам STT."""
    out: list[dict[str, Any]] = []
    processed_spans: set[tuple[int, int]] = set()

    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        et = str(item.get("entity_type", "")).strip().lower()
        if et not in ENTITY_TYPES:
            continue
        orig = item.get("original")
        if not isinstance(orig, str) or not orig.strip():
            continue
        orig_clean = orig.strip()
        if len(orig_clean) < 4:
            continue

        rep = item.get("replacement")
        rep_s = str(rep) if rep is not None else "[REDACTED]"

        needle = orig if orig in full_text else orig_clean
        if needle not in full_text:
            continue

        pattern = re.escape(needle)
        for match in re.finditer(pattern, full_text):
            cs, ce = match.start(), match.end()
            if (cs, ce) in processed_spans:
                continue
            processed_spans.add((cs, ce))

            t0, t1 = _char_span_to_time(segments, full_text, cs, ce)
            start_ms = _ms_from_sec_start(t0)
            end_ms = _ms_from_sec_end(t1)
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            out.append(
                {
                    "entity_type": et,
                    "original_text": full_text[cs:ce],
                    "replacement": rep_s,
                    "start_char": cs,
                    "end_char": ce,
                    "start_sec": round(t0, 3),
                    "end_sec": round(t1, 3),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
    return out


def _redaction_report(entities: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    spans: list[dict[str, Any]] = []
    for e in entities:
        t = e["entity_type"]
        counts[t] = counts.get(t, 0) + 1
        ex = str(e.get("original_text", ""))
        if len(ex) > 64:
            ex = ex[:61] + "…"
        examples.setdefault(t, [])
        if ex and ex not in examples[t][:20]:
            examples[t].append(ex)
        spans.append(
            {
                "type": t,
                "start_ms": e.get("start_ms", 0),
                "end_ms": e.get("end_ms", 0),
            }
        )
    return {"counts": counts, "examples": examples, "spans": spans}


def _redact_segment_text(seg_text: str, entities: list[dict[str, Any]]) -> str:
    """Маскирование в тексте сегмента по полям original_text сущностей, попавшим в эту подстроку."""
    t = seg_text
    relevant = []
    for e in entities:
        o = e.get("original_text")
        if isinstance(o, str) and o and o in t:
            relevant.append((t.find(o), o, str(e.get("replacement", "[REDACTED]"))))
    relevant.sort(key=lambda x: x[0], reverse=True)
    for _, o, rep in relevant:
        t = t.replace(o, rep)
    return t


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "llm_pii"}


@app.post("/v1/anonymize")
async def anonymize(
    _: Annotated[None, Depends(require_auth)],
    body: AnonymizeRequest,
) -> dict[str, Any]:
    segments = list(body.segments or [])
    full_text = body.text.strip()
    if segments:
        rebuilt = _full_text_from_segments(segments)
        if rebuilt:
            # Склейка сегментов пробелом — как у aggregate text в faster-whisper.
            full_text = rebuilt
    if not full_text:
        raise HTTPException(status_code=400, detail="empty transcript")

    messages = _build_llm_messages(full_text, body.language)
    raw_out = await _call_lm_studio(messages)

    try:
        parsed = _extract_json_object(raw_out)
    except ValueError:
        raise HTTPException(status_code=502, detail="model returned non-JSON output")

    raw_entities = parsed.get("entities")
    if not isinstance(raw_entities, list):
        raw_entities = []

    entities = _normalize_entities(raw_entities, full_text, segments)
    tr = _apply_redactions(
        full_text,
        [
            {
                "original": e["original_text"],
                "replacement": e.get("replacement", "[REDACTED]"),
                "start_char": e["start_char"],
                "end_char": e["end_char"],
            }
            for e in entities
        ],
    )

    report = _redaction_report(entities)

    out_segments: list[dict[str, Any]] = []
    if segments:
        for s in segments:
            rt = _redact_segment_text(s.text, entities)
            out_segments.append(
                {
                    "start": s.start,
                    "end": s.end,
                    "text": rt,
                    "words": [w.model_dump() for w in (s.words or [])],
                }
            )
    else:
        out_segments.append(
            {
                "start": 0.0,
                "end": 0.0,
                "text": tr,
                "words": None,
            }
        )

    return {
        "transcript_plain": full_text,
        "transcript_redacted": tr,
        "llm_entities": entities,
        "redaction_report": report,
        "segments": out_segments,
        "model": (os.getenv("LM_MODEL") or "").strip() or "gemma-3-4b-it",
    }


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8081"))
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
