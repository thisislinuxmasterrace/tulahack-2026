from __future__ import annotations

import json
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
    """Тело как у ответа STT: text + segments (таймкоды)."""

    text: str = ""
    segments: Optional[list[SegmentIn]] = None
    language: Optional[str] = None


def _full_text_from_segments(segments: list[SegmentIn]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def _segment_char_ranges(segments: list[SegmentIn]) -> list[tuple[int, int, float, float]]:
    """Для каждого сегмента: [char_start, char_end), start_sec, end_sec."""
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


def _char_span_to_time(segments: list[SegmentIn], full_text: str, cs: int, ce: int) -> tuple[float, float]:
    if not segments or ce <= cs:
        return 0.0, 0.0
    ranges = _segment_char_ranges(segments)
    if not ranges:
        return 0.0, 0.0
    t0: float | None = None
    t1: float | None = None
    for seg_start, seg_end, st, en in ranges:
        if seg_end <= cs or seg_start >= ce:
            continue
        if t0 is None:
            t0, t1 = st, en
        else:
            t0 = min(t0, st)
            t1 = max(t1, en)
    if t0 is None or t1 is None:
        return 0.0, 0.0
    return t0, t1


def _apply_redactions(text: str, entities: list[dict[str, Any]]) -> str:
    """Замены справа налево по позициям в тексте."""
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


# TODO защита от prompt injection??
def _build_llm_messages(user_text: str, language: str | None) -> list[dict[str, str]]:
    lang = language or "ru"
    system = (
        "Ты помогаешь анонимизировать персональные данные в расшифровке речи. "
        "Отвечай только валидным JSON без пояснений до или после."
    )
    user = f"""Язык текста: {lang}.

Текст расшифровки:
\"\"\"{user_text}\"\"\"

Найди все фрагменты, относящиеся к категориям (entity_type строго латиницей):
- passport — паспорт, серия/номер, паспортные данные
- inn — ИНН
- snils — СНИЛС
- phone — телефоны
- email — email
- address — адрес (улица, дом, квартира и т.п.)

Верни один JSON-объект формата:
{{
  "entities": [
    {{
      "entity_type": "passport|inn|snils|phone|email|address",
      "original": "точная цитата из текста выше",
      "replacement": "краткая маска на русском, например [ПАСПОРТ]"
    }}
  ],
  "transcript_redacted": "весь текст с подставленными replacement вместо чувствительных фрагментов"
}}

Правила:
- original должен дословно встречаться в тексте (скопируй подстроку).
- Не выдумывай данные; если сомневаешься — не включай.
- transcript_redacted — полная анонимизированная версия исходного текста."""
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


# ааааааааааааааааааааааа
def _normalize_entities(
    raw_entities: list[Any],
    full_text: str,
    segments: list[SegmentIn],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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
        rep = item.get("replacement")
        rep_s = str(rep) if rep is not None else "[REDACTED]"

        idx = full_text.find(orig)
        needle = orig
        if idx < 0:
            idx = full_text.find(orig_clean)
            needle = orig_clean
        if idx < 0:
            continue
        cs, ce = idx, idx + len(needle)
        t0, t1 = _char_span_to_time(segments, full_text, cs, ce)
        out.append(
            {
                "entity_type": et,
                "original_text": full_text[cs:ce],
                "replacement": rep_s,
                "start_char": cs,
                "end_char": ce,
                "start_sec": round(t0, 3),
                "end_sec": round(t1, 3),
                "start_ms": int(t0 * 1000),
                "end_ms": int(t1 * 1000),
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
    """Подстрочные замены по original_text, попавшим в сегмент."""
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
            # Как в STT: склейка через пробел — совпадает с полем text у Whisper.
            full_text = rebuilt
    elif not full_text:
        raise HTTPException(status_code=400, detail="empty transcript")
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
    transcript_redacted = parsed.get("transcript_redacted")
    if isinstance(transcript_redacted, str) and transcript_redacted.strip():
        tr = transcript_redacted.strip()
    else:
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
