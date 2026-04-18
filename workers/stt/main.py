from __future__ import annotations

import math
import os
import re
import tempfile
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from faster_whisper import BatchedInferencePipeline, WhisperModel

app = FastAPI(title="STT Worker", version="0.1.0")

_model: Optional[WhisperModel] = None
_batched_model: Optional[BatchedInferencePipeline] = None


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


def _segment_quality_from_whisper(seg: Any) -> tuple[float, float]:
    """avg_logprob (выше — увереннее), no_speech_prob (выше — скорее тишина/мусор)."""
    al = getattr(seg, "avg_logprob", None)
    ns = getattr(seg, "no_speech_prob", None)
    return (
        float(al) if al is not None else float("nan"),
        float(ns) if ns is not None else float("nan"),
    )


def get_model() -> BatchedInferencePipeline:
    global _model, _batched_model
    if _batched_model is None:
        name = os.getenv("WHISPER_MODEL", "large-v3")
        device = os.getenv("WHISPER_DEVICE", "cuda")
        ctype = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")
        _model = WhisperModel(name, device=device, compute_type=ctype)
        _batched_model = BatchedInferencePipeline(model=_model)
    return _batched_model


def _word_to_dict(w: Any) -> dict[str, Any]:
    return {
        "word": w.word,
        "start": float(w.start),
        "end": float(w.end),
        "probability": float(w.probability) if getattr(w, "probability", None) is not None else None,
    }


def _split_segment_by_max_duration(seg: Any, max_sec: float) -> list[dict[str, Any]]:
    """Дробит длинный сегмент по словам, чтобы фраза не была длиннее max_sec секунд."""
    avg_logprob, no_speech_prob = _segment_quality_from_whisper(seg)
    words = list(seg.words) if getattr(seg, "words", None) else []
    text_full = (seg.text or "").strip()
    span = float(seg.end) - float(seg.start)

    def _base(extra: dict[str, Any]) -> dict[str, Any]:
        d = dict(extra)
        d["avg_logprob"] = avg_logprob
        d["no_speech_prob"] = no_speech_prob
        return d

    if not words or max_sec <= 0 or span <= max_sec:
        return [
            _base(
                {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": text_full,
                    "words": [_word_to_dict(w) for w in words] if words else None,
                }
            )
        ]

    chunks: list[dict[str, Any]] = []
    cur: list[Any] = []
    cur_start: float | None = None

    for w in words:
        if not cur:
            cur = [w]
            cur_start = float(w.start)
            continue
        assert cur_start is not None
        if float(w.end) - cur_start > max_sec:
            t = "".join(x.word for x in cur).strip()
            chunks.append(
                _base(
                    {
                        "start": cur_start,
                        "end": float(cur[-1].end),
                        "text": t,
                        "words": [_word_to_dict(x) for x in cur],
                    }
                )
            )
            cur = [w]
            cur_start = float(w.start)
        else:
            cur.append(w)

    if cur and cur_start is not None:
        t = "".join(x.word for x in cur).strip()
        chunks.append(
            _base(
                {
                    "start": cur_start,
                    "end": float(cur[-1].end),
                    "text": t,
                    "words": [_word_to_dict(x) for x in cur],
                }
            )
        )

    return chunks


def _text_from_word_dicts(words: list[dict[str, Any]]) -> str:
    """Единый способ текста из токенов: как в faster-whisper (слитно, с пробелами внутри токенов)."""
    return "".join(w["word"] for w in words if w.get("word") is not None).strip()


def _finalize_segment(seg: dict[str, Any]) -> dict[str, Any]:
    """Синхронизирует text с words — иначе downstream считает позиции по text, а тайминги по words."""
    words = seg.get("words")
    if isinstance(words, list) and words:
        seg["text"] = _text_from_word_dicts(words)
    return seg


def _build_segments(segments_iter: Any, max_phrase_sec: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in segments_iter:
        for part in _split_segment_by_max_duration(seg, max_phrase_sec):
            out.append(_finalize_segment(part))
    return out


_RE_TAIL_SUBTITLE = re.compile(
    r"продолжение\s+следует|субтитр(ы|\s*сделал)|спасибо\s+за\s+просмотр",
    re.IGNORECASE | re.UNICODE,
)


def _trim_trailing_hallucination_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Срезает 1–2 последних субсегмента: типичные хвосты субтитров или очень сомнительные по no_speech/logprob."""
    if len(segments) < 2:
        return segments
    if os.getenv("WHISPER_TAIL_TRIM", "true").lower() not in ("1", "true", "yes"):
        return segments
    try:
        max_drop = min(4, max(0, int(os.getenv("WHISPER_TAIL_MAX_SEGMENTS", "2"))))
        ns_thr = float(os.getenv("WHISPER_TAIL_NO_SPEECH", "0.62"))
        al_thr = float(os.getenv("WHISPER_TAIL_AVG_LOGPROB", "-0.35"))
    except ValueError:
        max_drop, ns_thr, al_thr = 2, 0.62, -0.35

    out = list(segments)
    dropped = 0
    while len(out) >= 2 and dropped < max_drop:
        last = out[-1]
        text = (last.get("text") or "").strip()
        if not text:
            out.pop()
            dropped += 1
            continue
        tailish = len(text) <= 140 and _RE_TAIL_SUBTITLE.search(text)
        ns = last.get("no_speech_prob")
        al = last.get("avg_logprob")
        al_f = float(al) if isinstance(al, (int, float)) else float("nan")
        ns_f = float(ns) if isinstance(ns, (int, float)) else float("nan")
        dubious = (
            math.isfinite(al_f)
            and math.isfinite(ns_f)
            and ns_f >= ns_thr
            and al_f <= al_thr
        )
        if tailish or dubious:
            out.pop()
            dropped += 1
        else:
            break
    return out


def _strip_internal_segment_fields(segments: list[dict[str, Any]]) -> None:
    for s in segments:
        s.pop("avg_logprob", None)
        s.pop("no_speech_prob", None)


@app.on_event("startup")
def _load_model() -> None:
    get_model()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "stt"}


@app.post("/v1/transcribe")
async def transcribe(
    _: Annotated[None, Depends(require_auth)],
    file: UploadFile = File(...),
) -> dict:
    suffix = os.path.splitext(file.filename or "audio")[1] or ".wav"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    model = get_model()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = tmp.name

    word_ts = os.getenv("WHISPER_WORD_TIMESTAMPS", "true").lower() in ("1", "true", "yes")
    max_phrase = float(os.getenv("WHISPER_MAX_PHRASE_SEC", "8"))
    vad_ms = int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "500"))
    # По умолчанию True (как у faster-whisper): без контекста между окнами модель сильнее «фантазирует».
    # Хвостовые субтитровые галлюсинации режем отдельно (см. _trim_trailing_hallucination_segments).
    condition_on_previous = os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    _hall_raw = (os.getenv("WHISPER_HALLUCINATION_SILENCE_SEC") or "2").strip().lower()
    hallucination_silence_sec: float | None
    if _hall_raw in ("", "0", "false", "no"):
        hallucination_silence_sec = None
    else:
        try:
            hallucination_silence_sec = float(_hall_raw)
        except ValueError:
            hallucination_silence_sec = 2.0
    if not word_ts:
        hallucination_silence_sec = None
    _ns_raw = (os.getenv("WHISPER_NO_SPEECH_THRESHOLD") or "").strip()
    no_speech_threshold: float | None
    if _ns_raw:
        try:
            no_speech_threshold = float(_ns_raw)
        except ValueError:
            no_speech_threshold = None
    else:
        no_speech_threshold = None

    try:
        transcribe_kw: dict[str, Any] = {
            "language": os.getenv("WHISPER_LANGUAGE") or None,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": vad_ms},
            "word_timestamps": word_ts,
            "condition_on_previous_text": condition_on_previous,
        }
        if hallucination_silence_sec is not None:
            transcribe_kw["hallucination_silence_threshold"] = hallucination_silence_sec
        if no_speech_threshold is not None:
            transcribe_kw["no_speech_threshold"] = no_speech_threshold
        segments_iter, info = model.transcribe(path, **transcribe_kw)
        segments = _build_segments(segments_iter, max_phrase if word_ts else 1e9)
        segments = _trim_trailing_hallucination_segments(segments)
        _strip_internal_segment_fields(segments)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    text = " ".join(s["text"].strip() for s in segments)

    return {
        "text": text,
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
    }
