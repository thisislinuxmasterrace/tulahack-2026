from __future__ import annotations

import math
import os
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ner import gliner_model_name
from pipeline import detect

app = FastAPI(title="PII Worker (GLiNER2 + Natasha + rules)", version="0.2.0")

# Сущности без своей русской метки в контракте фронта/шлюза; REPLACEMENTS — подстановка в тексте.
REPLACEMENTS = {
    "passport": "[ПАСПОРТ]",
    "inn": "[ИНН]",
    "snils": "[СНИЛС]",
    "phone": "[ТЕЛЕФОН]",
    "email": "[EMAIL]",
    "address": "[АДРЕС]",
    "person": "[ИМЯ]",
}


def _model_label() -> str:
    use_natasha = os.getenv("USE_NATASHA", "1") != "0"
    return gliner_model_name() + ("+natasha" if use_natasha else "") + "+rules"


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


def _spans_to_entities(
    spans: list[Any],
    full_text: str,
    segments: list[SegmentIn],
) -> list[dict[str, Any]]:
    """Span -> сущность контракта: символьные границы и интервалы времени по сегментам STT."""
    out: list[dict[str, Any]] = []
    for sp in spans:
        cs, ce = sp.start, sp.end
        t0, t1 = _char_span_to_time(segments, full_text, cs, ce)
        start_ms = _ms_from_sec_start(t0)
        end_ms = _ms_from_sec_end(t1)
        if end_ms <= start_ms:
            end_ms = start_ms + 1
        out.append(
            {
                "entity_type": sp.type,
                "original_text": full_text[cs:ce],
                "replacement": REPLACEMENTS.get(sp.type, "[REDACTED]"),
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
    return {"status": "ok", "service": "pii_gliner"}


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
        # Нет речи / пустой STT — не дергаем LLM, отдаём тот же контракт ответа, что и после анонимизации.
        empty_report = _redaction_report([])
        out_empty: list[dict[str, Any]] = []
        if segments:
            for s in segments:
                out_empty.append(
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text or "",
                        "words": [w.model_dump() for w in (s.words or [])],
                    }
                )
        else:
            out_empty.append(
                {
                    "start": 0.0,
                    "end": 0.0,
                    "text": "",
                    "words": None,
                }
            )
        return {
            "transcript_plain": "",
            "transcript_redacted": "",
            "llm_entities": [],
            "redaction_report": empty_report,
            "segments": out_empty,
            "model": _model_label(),
        }

    spans = await run_in_threadpool(detect, full_text)
    entities = _spans_to_entities(spans, full_text, segments)
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
        "model": _model_label(),
    }


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8081"))
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
