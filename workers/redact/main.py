from __future__ import annotations

import json
import os
from io import BytesIO
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydub import AudioSegment
from pydub.generators import Sine

app = FastAPI(title="Audio redact worker", version="0.1.0")


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


def load_spans(data: dict[str, Any]) -> list[dict[str, Any]]:
    spans = (data.get("redaction_report") or {}).get("spans") or []
    if not spans:
        spans = [
            {"start_ms": int(ent["start_ms"]), "end_ms": int(ent["end_ms"])}
            for ent in (data.get("llm_entities") or [])
            if isinstance(ent, dict)
            and "start_ms" in ent
            and "end_ms" in ent
        ]
    return [s for s in spans if isinstance(s, dict)]


def export_format_and_mime(filename: str | None, content_type: str | None) -> tuple[str, str, dict[str, Any]]:
    """
    Формат выхода как у входного файла (расширение или Content-Type).
    Возвращает: имя формата pydub/ffmpeg, Media-Type ответа, kwargs для export().
    """
    name = (filename or "").strip()
    ext = os.path.splitext(name)[1].lower()
    by_ext: dict[str, tuple[str, str]] = {
        ".mp3": ("mp3", "audio/mpeg"),
        ".wav": ("wav", "audio/wav"),
        ".wave": ("wav", "audio/wav"),
        ".ogg": ("ogg", "audio/ogg"),
        ".oga": ("ogg", "audio/ogg"),
        ".opus": ("opus", "audio/ogg"),
        ".webm": ("webm", "audio/webm"),
        ".flac": ("flac", "audio/flac"),
        ".m4a": ("ipod", "audio/mp4"),
        ".aac": ("adts", "audio/aac"),
    }
    if ext in by_ext:
        fmt, mime = by_ext[ext]
        extra: dict[str, Any] = {}
        if fmt == "ipod":
            extra["codec"] = "aac"
        return fmt, mime, extra

    ct = (content_type or "").split(";")[0].strip().lower()
    by_ct: dict[str, tuple[str, str]] = {
        "audio/mpeg": ("mp3", "audio/mpeg"),
        "audio/mp3": ("mp3", "audio/mpeg"),
        "audio/wav": ("wav", "audio/wav"),
        "audio/x-wav": ("wav", "audio/wav"),
        "audio/wave": ("wav", "audio/wav"),
        "audio/ogg": ("ogg", "audio/ogg"),
        "audio/webm": ("webm", "audio/webm"),
        "audio/flac": ("flac", "audio/flac"),
        "audio/mp4": ("ipod", "audio/mp4"),
        "audio/x-m4a": ("ipod", "audio/mp4"),
        "audio/aac": ("adts", "audio/aac"),
    }
    if ct in by_ct:
        fmt, mime = by_ct[ct]
        extra: dict[str, Any] = {}
        if fmt == "ipod":
            extra["codec"] = "aac"
        return fmt, mime, extra

    return "wav", "audio/wav", {}


def _end_pad_ms() -> int:
    """Доп. миллисекунды к концу каждого span (после LLM), если в пике всё ещё слышна часть цифры."""
    try:
        return max(0, int(os.getenv("REDACT_END_PAD_MS", "80")))
    except ValueError:
        return 80


def apply_beep(audio: AudioSegment, spans: list[dict[str, Any]], freq: int = 1000, gain_db: int = -5) -> AudioSegment:
    pad = _end_pad_ms()
    audio_len = len(audio)
    spans = sorted(spans, key=lambda x: int(x.get("start_ms", 0)), reverse=True)
    for span in spans:
        start = int(span.get("start_ms", 0))
        end = int(span.get("end_ms", 0))
        if pad:
            end = min(audio_len, end + pad)
        duration = end - start
        if duration <= 0:
            continue
        beep = Sine(freq).to_audio_segment(duration=duration).apply_gain(gain_db)
        audio = audio[:start] + beep + audio[end:]
    return audio


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "audio_redact"}


@app.post("/v1/redact")
async def redact(
    _: Annotated[None, Depends(require_auth)],
    file: UploadFile = File(...),
    report: str = Form(...),
    freq: int = Form(1000),
    gain_db: int = Form(-5),
) -> Response:
    """
    Multipart: file — исходное аудио; report — JSON с полями redaction_report и/или llm_entities
    (как в processing_jobs после LLM). Ответ — тот же контейнер/кодек, что у входа (по имени файла или Content-Type).
    """
    raw = (report or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="missing report JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid report JSON: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="report must be a JSON object")

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        audio = AudioSegment.from_file(BytesIO(audio_bytes))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"could not decode audio: {e}") from e

    spans = load_spans(data)
    if spans:
        audio = apply_beep(audio, spans, freq=freq, gain_db=gain_db)

    fmt, mime, export_kw = export_format_and_mime(file.filename, file.content_type)
    out = BytesIO()
    try:
        audio.export(out, format=fmt, **export_kw)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"could not encode audio as {fmt}: {e}",
        ) from e
    body = out.getvalue()
    return Response(content=body, media_type=mime)


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8082"))
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
