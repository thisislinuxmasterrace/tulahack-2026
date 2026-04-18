from __future__ import annotations

import os
import tempfile
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from faster_whisper import WhisperModel

app = FastAPI(title="STT Worker", version="0.1.0")

_model: Optional[WhisperModel] = None


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


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        name = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "cuda")
        ctype = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
        _model = WhisperModel(name, device=device, compute_type=ctype)
    return _model


def _word_to_dict(w: Any) -> dict[str, Any]:
    return {
        "word": w.word,
        "start": float(w.start),
        "end": float(w.end),
        "probability": float(w.probability) if getattr(w, "probability", None) is not None else None,
    }


def _split_segment_by_max_duration(seg: Any, max_sec: float) -> list[dict[str, Any]]:
    """Дробит длинный сегмент по словам, чтобы фраза не была длиннее max_sec секунд."""
    words = list(seg.words) if getattr(seg, "words", None) else []
    text_full = (seg.text or "").strip()
    span = float(seg.end) - float(seg.start)

    if not words or max_sec <= 0 or span <= max_sec:
        return [
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": text_full,
                "words": [_word_to_dict(w) for w in words] if words else None,
            }
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
                {
                    "start": cur_start,
                    "end": float(cur[-1].end),
                    "text": t,
                    "words": [_word_to_dict(x) for x in cur],
                }
            )
            cur = [w]
            cur_start = float(w.start)
        else:
            cur.append(w)

    if cur and cur_start is not None:
        t = "".join(x.word for x in cur).strip()
        chunks.append(
            {
                "start": cur_start,
                "end": float(cur[-1].end),
                "text": t,
                "words": [_word_to_dict(x) for x in cur],
            }
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

    try:
        segments_iter, info = model.transcribe(
            path,
            language=os.getenv("WHISPER_LANGUAGE") or None,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": vad_ms},
            word_timestamps=word_ts,
        )
        segments = _build_segments(segments_iter, max_phrase if word_ts else 1e9)
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
