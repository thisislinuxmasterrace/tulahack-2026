"""
Оркестратор (asyncio): Redis -> MinIO -> STT -> LLM -> Redact.

Стадии: audio.process -> audio.llm -> audio.redact в одном Redis-списке.
Одна реплика runner может параллельно обрабатывать до RUNNER_MAX_CONCURRENCY задач
(HTTP к воркерам не блокируют друг друга).

Соединения PostgreSQL берутся из пула только на короткие транзакции (не на время HTTP).
MinIO: отдельный клиент на каждый sync-вызов внутри to_thread (без общего mutable state).
httpx.Limits поднят под max_concurrency, чтобы не упираться в дефолтный пул соединений.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

import httpx
import redis.asyncio as redis_async
from minio import Minio
from psycopg_pool import AsyncConnectionPool
from redis.exceptions import RedisError

LOG = logging.getLogger("runner")

JOB_AUDIO_PROCESS = "audio.process"
JOB_AUDIO_LLM = "audio.llm"
JOB_AUDIO_REDACT = "audio.redact"

T = TypeVar("T")


def chain_payload(src: dict[str, Any], new_type: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": new_type,
        "upload_id": src["upload_id"],
        "user_id": src["user_id"],
        "processing_job_id": src["processing_job_id"],
        "bucket": src["bucket"],
        "object_key": src["object_key"],
        "retry_count": int(src.get("retry_count") or 0),
    }
    if "created_at" in src:
        out["created_at"] = src["created_at"]
    return out


async def enqueue_queue(
    settings: "Settings", r: redis_async.Redis, payload: dict[str, Any]
) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    await r.lpush(settings.queue_key, raw)


def _http_retry_config() -> tuple[int, float]:
    attempts = int(os.getenv("HTTP_MAX_ATTEMPTS", "5"))
    base = float(os.getenv("HTTP_RETRY_BASE_SEC", "1.0"))
    return max(1, attempts), max(0.1, base)


def _max_queue_retries() -> int:
    return max(0, int(os.getenv("WORKER_QUEUE_RETRIES", "4")))


def _is_transient_http_exc(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (502, 503, 504)
    return False


async def http_call_with_retry(
    label: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    max_attempts, base = _http_retry_config()
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code in (502, 503, 504) and attempt < max_attempts:
                delay = base * (2 ** (attempt - 1))
                LOG.warning(
                    "%s: HTTP %s, попытка %s/%s, повтор через %.1fs",
                    label,
                    e.response.status_code,
                    attempt,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ) as e:
            last = e
            if attempt < max_attempts:
                delay = base * (2 ** (attempt - 1))
                LOG.warning(
                    "%s: %s, попытка %s/%s, повтор через %.1fs",
                    label,
                    e,
                    attempt,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
    assert last is not None
    raise last


async def _requeue_after_transient(
    settings: Settings,
    r: redis_async.Redis,
    pool: AsyncConnectionPool,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    exc: BaseException,
) -> bool:
    if not _is_transient_http_exc(exc):
        return False
    n = int(payload.get("retry_count") or 0)
    if n >= _max_queue_retries():
        LOG.error(
            "job %s: исчерпаны повторы очереди (%s), фиксируем failed",
            job_id,
            _max_queue_retries(),
        )
        return False
    new_payload = dict(payload)
    new_payload["retry_count"] = n + 1
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = 'queued',
                            stage = NULL,
                            error_code = NULL,
                            error_message = NULL,
                            started_at = NULL,
                            finished_at = NULL,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (str(job_id),),
                    )
                    await append_event(
                        cur,
                        job_id,
                        "warning",
                        f"Сетевая ошибка до сохранения STT: {exc!s}; возврат в очередь (попытка {n + 2})",
                    )
        raw = json.dumps(new_payload, ensure_ascii=False)
        await r.lpush(settings.queue_key, raw)
        await set_job_status_cache(r, payload, job_id, "queued")
        LOG.info("job %s requeued (retry_count=%s)", job_id, n + 1)
        return True
    except Exception:
        LOG.exception("requeue failed for job %s", job_id)
        return False


async def _requeue_llm_after_transient(
    settings: Settings,
    r: redis_async.Redis,
    pool: AsyncConnectionPool,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    exc: BaseException,
) -> bool:
    if not _is_transient_http_exc(exc):
        return False
    n = int(payload.get("retry_count") or 0)
    if n >= _max_queue_retries():
        LOG.error(
            "job %s: исчерпаны повторы очереди (LLM, %s), фиксируем failed",
            job_id,
            _max_queue_retries(),
        )
        return False
    new_payload = chain_payload(payload, JOB_AUDIO_LLM)
    new_payload["retry_count"] = n + 1
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = 'llm',
                            stage = 'llm',
                            error_code = NULL,
                            error_message = NULL,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (str(job_id),),
                    )
                    await append_event(
                        cur,
                        job_id,
                        "warning",
                        f"Сетевая ошибка при LLM: {exc!s}; возврат в очередь (попытка {n + 2})",
                    )
        raw = json.dumps(new_payload, ensure_ascii=False)
        await r.lpush(settings.queue_key, raw)
        await set_job_status_cache(r, payload, job_id, "llm")
        LOG.info("job %s requeued after LLM transient (retry_count=%s)", job_id, n + 1)
        return True
    except Exception:
        LOG.exception("requeue llm failed for job %s", job_id)
        return False


async def _requeue_redact_after_transient(
    settings: Settings,
    r: redis_async.Redis,
    pool: AsyncConnectionPool,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    exc: BaseException,
) -> bool:
    if not _is_transient_http_exc(exc):
        return False
    n = int(payload.get("retry_count") or 0)
    if n >= _max_queue_retries():
        LOG.error(
            "job %s: исчерпаны повторы очереди (redact, %s), фиксируем failed",
            job_id,
            _max_queue_retries(),
        )
        return False
    new_payload = chain_payload(payload, JOB_AUDIO_REDACT)
    new_payload["retry_count"] = n + 1
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = 'render_audio',
                            stage = 'redact',
                            error_code = NULL,
                            error_message = NULL,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (str(job_id),),
                    )
                    await append_event(
                        cur,
                        job_id,
                        "warning",
                        f"Сетевая ошибка при redact: {exc!s}; возврат в очередь (попытка {n + 2})",
                    )
        raw = json.dumps(new_payload, ensure_ascii=False)
        await r.lpush(settings.queue_key, raw)
        await set_job_status_cache(r, payload, job_id, "render_audio")
        LOG.info("job %s requeued after redact transient (retry_count=%s)", job_id, n + 1)
        return True
    except Exception:
        LOG.exception("requeue redact failed for job %s", job_id)
        return False


@dataclass(frozen=True)
class Settings:
    redis_url: str
    queue_key: str
    database_url: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_use_ssl: bool
    s3_public_base_url: str
    stt_base_url: str
    llm_base_url: str
    redact_base_url: str
    worker_token: str
    stt_timeout_sec: float
    llm_timeout_sec: float
    redact_timeout_sec: float
    brpop_timeout_sec: int
    max_concurrency: int


def _require_worker_urls(settings: Settings) -> None:
    missing = [
        name
        for name, url in (
            ("STT_BASE_URL", settings.stt_base_url),
            ("LLM_BASE_URL", settings.llm_base_url),
            ("REDACT_BASE_URL", settings.redact_base_url),
        )
        if not url
    ]
    if missing:
        LOG.error(
            "runner: задайте обязательные URL воркеров: %s",
            ", ".join(missing),
        )
        sys.exit(1)
    if not settings.s3_public_base_url:
        LOG.error("runner: S3_PUBLIC_BASE_URL обязателен (ссылка на redacted-аудио в MinIO)")
        sys.exit(1)


def load_settings() -> Settings:
    return Settings(
        redis_url=os.environ["REDIS_URL"].strip(),
        queue_key=os.getenv("REDIS_AUDIO_QUEUE_KEY", "tulahack:queue:audio:process").strip(),
        database_url=os.environ["DATABASE_URL"].strip(),
        s3_endpoint=os.environ["S3_ENDPOINT"].strip(),
        s3_access_key=os.environ["S3_ACCESS_KEY"].strip(),
        s3_secret_key=os.environ["S3_SECRET_KEY"].strip(),
        s3_bucket=os.environ["S3_BUCKET"].strip(),
        s3_use_ssl=os.getenv("S3_USE_SSL", "false").lower() in ("1", "true", "yes"),
        s3_public_base_url=os.getenv("S3_PUBLIC_BASE_URL", "").rstrip("/"),
        stt_base_url=os.getenv("STT_BASE_URL", "").rstrip("/"),
        llm_base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
        redact_base_url=os.getenv("REDACT_BASE_URL", "").rstrip("/"),
        worker_token=(os.getenv("WORKER_TOKEN") or "").strip(),
        stt_timeout_sec=float(os.getenv("STT_HTTP_TIMEOUT_SEC", "600")),
        # По умолчанию 600 с — как LM_HTTP_TIMEOUT_SEC к LM Studio в воркере; при необходимости увеличьте в env.
        llm_timeout_sec=float(os.getenv("LLM_HTTP_TIMEOUT_SEC", "600")),
        redact_timeout_sec=float(os.getenv("REDACT_HTTP_TIMEOUT_SEC", "600")),
        brpop_timeout_sec=int(os.getenv("REDIS_BRPOP_TIMEOUT_SEC", "5")),
        max_concurrency=max(1, int(os.getenv("RUNNER_MAX_CONCURRENCY", "32"))),
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    if not settings.worker_token:
        return {}
    return {"Authorization": f"Bearer {settings.worker_token}"}


def minio_client(settings: Settings) -> Minio:
    return Minio(
        settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_use_ssl,
    )


def _minio_fget_sync(settings: Settings, bucket: str, object_key: str, file_path: str) -> None:
    """Отдельный клиент на вызов — безопасно при concurrent to_thread."""
    minio_client(settings).fget_object(bucket, object_key, file_path)


def _minio_put_sync(
    settings: Settings,
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str,
) -> None:
    minio_client(settings).put_object(
        bucket,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


async def minio_fget(
    settings: Settings, bucket: str, object_key: str, file_path: str
) -> None:
    await asyncio.to_thread(_minio_fget_sync, settings, bucket, object_key, file_path)


async def minio_put_bytes(
    settings: Settings,
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str,
) -> None:
    await asyncio.to_thread(_minio_put_sync, settings, bucket, object_key, data, content_type)


async def append_event(
    cur: Any, job_id: uuid.UUID, level: str, message: str
) -> None:
    ev = json.dumps(
        [{"ts": datetime.now(timezone.utc).isoformat(), "level": level, "message": message}],
        ensure_ascii=False,
    )
    await cur.execute(
        """
        UPDATE processing_jobs
        SET processing_events = coalesce(processing_events, '[]'::jsonb) || %s::jsonb,
            updated_at = now()
        WHERE id = %s
        """,
        (ev, str(job_id)),
    )


async def set_job_status(
    cur: Any,
    job_id: uuid.UUID,
    status: str,
    *,
    stage: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    await cur.execute(
        """
        UPDATE processing_jobs
        SET status = %s,
            stage = COALESCE(%s, stage),
            error_code = COALESCE(%s, error_code),
            error_message = COALESCE(%s, error_message),
            started_at = CASE WHEN %s IN ('running', 'stt', 'llm', 'render_audio') AND started_at IS NULL THEN now() ELSE started_at END,
            updated_at = now()
        WHERE id = %s
        """,
        (status, stage, error_code, error_message, status, str(job_id)),
    )


async def run_stt(
    settings: Settings,
    client: httpx.AsyncClient,
    file_path: str,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    url = f"{settings.stt_base_url}/v1/transcribe"

    async def once() -> dict[str, Any]:
        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        data = await asyncio.to_thread(_read)
        files = {"file": (filename, data, content_type or "application/octet-stream")}
        r = await client.post(
            url,
            files=files,
            timeout=settings.stt_timeout_sec,
        )
        r.raise_for_status()
        return r.json()

    return await http_call_with_retry("STT", once)


def _llm_request_strip_word_timestamps() -> bool:
    """Убирает words[] из сегментов в JSON к LLM (по умолчанию вкл.) — иначе тело POST раздувается до десятков МБ."""
    return os.getenv("LLM_REQUEST_STRIP_WORD_TIMESTAMPS", "true").lower() in ("1", "true", "yes")


def _segments_for_llm_payload(segments: Any, *, strip_words: bool) -> Any:
    """
    Сжимает сегменты для POST /v1/anonymize.

    В промпт нейросети попадает только склеенный текст (full_text), не words — см. workers/llm _build_llm_messages.

    Поле segments нужно воркеру для привязки сущностей ко времени аудио: достаточно start/end/text.
    Без words workers/llm использует пропорциональный fallback в _local_span_to_times_in_segment (чуть грубее бип,
    чем с word timestamps). Полные segments с words остаются в БД в whisper_output — UI и хранение не теряют их.
    """
    if not strip_words or not isinstance(segments, list) or not segments:
        return segments
    compact: list[dict[str, Any]] = []
    for s in segments:
        if not isinstance(s, dict):
            continue
        t = s.get("text")
        compact.append(
            {
                "start": s.get("start"),
                "end": s.get("end"),
                "text": t if isinstance(t, str) else "",
            }
        )
    return compact


async def run_llm(
    settings: Settings,
    client: httpx.AsyncClient,
    stt_body: dict[str, Any],
) -> dict[str, Any]:
    url = f"{settings.llm_base_url}/v1/anonymize"
    strip = _llm_request_strip_word_timestamps()
    segs = _segments_for_llm_payload(stt_body.get("segments"), strip_words=strip)
    body = {
        "text": stt_body.get("text") or "",
        "segments": segs,
        "language": stt_body.get("language"),
    }
    txt = body["text"] or ""
    nseg = len(segs) if isinstance(segs, list) else 0
    LOG.info(
        "LLM anonymize POST: text_len=%d segment_count=%d strip_word_timestamps=%s",
        len(txt),
        nseg,
        strip,
    )

    async def once() -> dict[str, Any]:
        r = await client.post(
            url,
            json=body,
            timeout=settings.llm_timeout_sec,
        )
        r.raise_for_status()
        return r.json()

    return await http_call_with_retry("LLM", once)


async def run_redact(
    settings: Settings,
    client: httpx.AsyncClient,
    file_path: str,
    filename: str,
    content_type: str,
    report_payload: dict[str, Any],
) -> tuple[bytes, str]:
    url = f"{settings.redact_base_url}/v1/redact"

    async def once() -> tuple[bytes, str]:
        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        data = await asyncio.to_thread(_read)
        files = {"file": (filename, data, content_type or "application/octet-stream")}
        data_form = {"report": json.dumps(report_payload, ensure_ascii=False)}
        r = await client.post(
            url,
            files=files,
            data=data_form,
            timeout=settings.redact_timeout_sec,
        )
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
        return r.content, ct

    return await http_call_with_retry("redact", once)


def whisper_output_from_stt(stt: dict[str, Any]) -> dict[str, Any]:
    return {
        "language": stt.get("language"),
        "duration_sec": stt.get("duration"),
        "segments": stt.get("segments") or [],
        "text": stt.get("text") or "",
    }


def job_status_cache_key(upload_id: str) -> str:
    p = (os.getenv("REDIS_JOB_STATUS_KEY_PREFIX") or "").strip() or "tulahack:job:status:"
    if not p.endswith(":"):
        p += ":"
    return p + upload_id


def job_events_channel(upload_id: str) -> str:
    p = (os.getenv("REDIS_JOB_EVENTS_CHANNEL_PREFIX") or "").strip() or "tulahack:job:events:"
    if not p.endswith(":"):
        p += ":"
    return p + upload_id


async def set_job_status_cache(
    r: redis_async.Redis,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    ttl = int(os.getenv("REDIS_JOB_STATUS_TTL_SEC", "172800"))
    body: dict[str, Any] = {
        "processing_job_id": str(job_id),
        "upload_id": payload["upload_id"],
        "user_id": payload["user_id"],
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["error_message"] = error_message[:500]
    key = job_status_cache_key(str(payload["upload_id"]))
    body_json = json.dumps(body, ensure_ascii=False)
    try:
        await r.setex(key, ttl, body_json)
        await r.publish(job_events_channel(str(payload["upload_id"])), body_json)
        LOG.info("redis job status: key=%s status=%s", key, status)
    except RedisError as e:
        LOG.warning("redis SET/PUBLISH job status failed: %s", e)


async def _fail_job(
    settings: Settings,
    r: redis_async.Redis,
    pool: AsyncConnectionPool,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    exc: BaseException,
) -> None:
    LOG.exception("job %s failed: %s", job_id, exc)
    msg = str(exc)[:2000]
    err_code = "network_error" if _is_transient_http_exc(exc) else "pipeline_error"
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await set_job_status(
                        cur,
                        job_id,
                        "failed",
                        stage="failed",
                        error_code=err_code,
                        error_message=msg,
                    )
                    await append_event(cur, job_id, "error", msg)
                    await cur.execute(
                        "UPDATE processing_jobs SET finished_at = now(), updated_at = now() WHERE id = %s",
                        (str(job_id),),
                    )
    except Exception:
        LOG.exception("could not persist failed status for job %s", job_id)
    else:
        await set_job_status_cache(r, payload, job_id, "failed", error_message=msg)


async def process_audio_stt(
    settings: Settings,
    pool: AsyncConnectionPool,
    http: httpx.AsyncClient,
    r: redis_async.Redis,
    payload: dict[str, Any],
) -> None:
    job_id = uuid.UUID(payload["processing_job_id"])
    bucket = payload["bucket"]
    object_key = payload["object_key"]

    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT whisper_output, status FROM processing_jobs WHERE id = %s",
                    (str(job_id),),
                )
                row = await cur.fetchone()

    if not row:
        raise RuntimeError(f"processing_jobs {job_id} не найдена")

    if row[0] is not None:
        st = row[1]
        if st in ("render_audio", "done"):
            LOG.info("job %s: STT уже пройден, пропуск", job_id)
            return
        if st in ("failed", "cancelled"):
            LOG.info("job %s: задача в статусе %s, пропуск", job_id, st)
            return
        await enqueue_queue(settings, r, chain_payload(payload, JOB_AUDIO_LLM))
        LOG.info("job %s: whisper уже в БД — следующая стадия в очереди (LLM)", job_id)
        return

    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await set_job_status(cur, job_id, "running", stage="download")
                await append_event(cur, job_id, "info", "Задача получена из Redis (STT)")

    await set_job_status_cache(r, payload, job_id, "running")

    ext = os.path.splitext(object_key)[1] or ".wav"
    tmp_path: str | None = None
    stt_persisted = False
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
        await minio_fget(settings, bucket, object_key, tmp_path)

        orig_name = os.path.basename(object_key)
        content_type = "application/octet-stream"

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await set_job_status(cur, job_id, "stt", stage="stt")
                    await append_event(cur, job_id, "info", "Файл скачан из MinIO, запрос к STT")

        await set_job_status_cache(r, payload, job_id, "stt")

        if not settings.stt_base_url:
            raise RuntimeError("STT_BASE_URL is not set")

        stt = await run_stt(settings, http, tmp_path, orig_name, content_type)
        whisper_json = whisper_output_from_stt(stt)

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = %s,
                            stage = %s,
                            whisper_model = COALESCE(%s, whisper_model),
                            whisper_output = %s::jsonb,
                            transcript_plain = %s,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (
                            "llm",
                            "llm",
                            os.getenv("WHISPER_MODEL"),
                            json.dumps(whisper_json, ensure_ascii=False),
                            stt.get("text") or "",
                            str(job_id),
                        ),
                    )
                    await append_event(cur, job_id, "info", "STT завершён, следующая стадия в очереди (LLM)")

        await set_job_status_cache(r, payload, job_id, "llm")
        stt_persisted = True

        await enqueue_queue(settings, r, chain_payload(payload, JOB_AUDIO_LLM))
        LOG.info("job %s: STT готов, в очередь добавлена стадия LLM", job_id)

    except Exception as e:
        if not stt_persisted and await _requeue_after_transient(
            settings, r, pool, payload, job_id, e
        ):
            return
        await _fail_job(settings, r, pool, payload, job_id, e)
    finally:
        if tmp_path:
            try:
                await asyncio.to_thread(os.unlink, tmp_path)
            except OSError:
                pass


async def process_audio_llm(
    settings: Settings,
    pool: AsyncConnectionPool,
    http: httpx.AsyncClient,
    r: redis_async.Redis,
    payload: dict[str, Any],
) -> None:
    job_id = uuid.UUID(payload["processing_job_id"])
    llm_persisted = False
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT whisper_output, transcript_plain, status FROM processing_jobs WHERE id = %s",
                        (str(job_id),),
                    )
                    row = await cur.fetchone()

        if not row:
            raise RuntimeError(f"processing_jobs {job_id} не найдена")
        whisper_out, transcript_plain, status = row[0], row[1], row[2]

        if status in ("render_audio", "done"):
            LOG.info("job %s: LLM уже выполнен, пропуск", job_id)
            return
        if status in ("failed", "cancelled"):
            LOG.info("job %s: задача в статусе %s, пропуск LLM", job_id, status)
            return
        if whisper_out is None:
            raise RuntimeError("whisper_output пуст — нельзя выполнить LLM")

        whisper_json = whisper_out if isinstance(whisper_out, dict) else {}
        stt_for_llm: dict[str, Any] = dict(whisper_json)
        stt_for_llm["text"] = transcript_plain or stt_for_llm.get("text") or ""

        if not settings.llm_base_url:
            raise RuntimeError("LLM_BASE_URL is not set")

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await append_event(cur, job_id, "info", "Стадия LLM получена из очереди")

        llm = await run_llm(settings, http, stt_for_llm)
        entities = llm.get("llm_entities")
        report = llm.get("redaction_report")

        if not settings.redact_base_url:
            raise RuntimeError("REDACT_BASE_URL is not set")

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = %s,
                            stage = %s,
                            llm_model = COALESCE(%s, llm_model),
                            llm_entities = %s::jsonb,
                            transcript_plain = %s,
                            transcript_redacted = %s,
                            redaction_report = %s::jsonb,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (
                            "render_audio",
                            "redact",
                            os.getenv("LM_MODEL"),
                            json.dumps(entities, ensure_ascii=False) if entities is not None else None,
                            llm.get("transcript_plain"),
                            llm.get("transcript_redacted"),
                            json.dumps(report, ensure_ascii=False) if report is not None else None,
                            str(job_id),
                        ),
                    )
                    await append_event(cur, job_id, "info", "LLM завершён, следующая стадия в очереди (redact)")

        await set_job_status_cache(r, payload, job_id, "render_audio")
        llm_persisted = True

        await enqueue_queue(settings, r, chain_payload(payload, JOB_AUDIO_REDACT))
        LOG.info("job %s: LLM готов, в очередь добавлена стадия redact", job_id)

    except Exception as e:
        if not llm_persisted and await _requeue_llm_after_transient(
            settings, r, pool, payload, job_id, e
        ):
            return
        await _fail_job(settings, r, pool, payload, job_id, e)


async def process_audio_redact(
    settings: Settings,
    pool: AsyncConnectionPool,
    http: httpx.AsyncClient,
    r: redis_async.Redis,
    payload: dict[str, Any],
) -> None:
    job_id = uuid.UUID(payload["processing_job_id"])
    bucket = payload["bucket"]
    object_key = payload["object_key"]

    ext = os.path.splitext(object_key)[1] or ".wav"
    tmp_path: str | None = None
    redact_done = False
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT status, llm_entities, redaction_report
                        FROM processing_jobs WHERE id = %s
                        """,
                        (str(job_id),),
                    )
                    row = await cur.fetchone()

        if not row:
            raise RuntimeError(f"processing_jobs {job_id} не найдена")
        status, entities, report = row[0], row[1], row[2]

        if status == "done":
            LOG.info("job %s: redact уже выполнен, пропуск", job_id)
            return
        if status in ("failed", "cancelled"):
            LOG.info("job %s: задача в статусе %s, пропуск redact", job_id, status)
            return
        if status != "render_audio":
            LOG.warning("job %s: ожидался render_audio, статус %s", job_id, status)

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
        await minio_fget(settings, bucket, object_key, tmp_path)

        orig_name = os.path.basename(object_key)
        content_type = "application/octet-stream"

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await append_event(cur, job_id, "info", "Стадия redact получена из очереди")

        await set_job_status_cache(r, payload, job_id, "render_audio")

        report_payload: dict[str, Any] = {
            "llm_entities": entities,
            "redaction_report": report,
        }
        redacted_bytes, redacted_ct = await run_redact(
            settings, http, tmp_path, orig_name, content_type, report_payload
        )
        ext_out = os.path.splitext(orig_name)[1] or ".wav"
        redact_key = f"redacted/{payload['upload_id']}/{job_id}{ext_out}"

        await minio_put_bytes(
            settings,
            settings.s3_bucket,
            redact_key,
            redacted_bytes,
            redacted_ct or "application/octet-stream",
        )
        public_base = settings.s3_public_base_url
        if not public_base:
            raise RuntimeError("S3_PUBLIC_BASE_URL is not set (нужен публичный URL для redacted_audio_storage_url)")
        redacted_url = f"{public_base}/{settings.s3_bucket}/{redact_key}"

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE processing_jobs
                        SET status = %s,
                            stage = %s,
                            redacted_audio_bucket = %s,
                            redacted_audio_object_key = %s,
                            redacted_audio_storage_url = %s,
                            finished_at = now(),
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (
                            "done",
                            "done",
                            settings.s3_bucket,
                            redact_key,
                            redacted_url,
                            str(job_id),
                        ),
                    )
                    await append_event(cur, job_id, "info", "Обработка завершена (redact аудио в MinIO)")

        await set_job_status_cache(r, payload, job_id, "done")
        redact_done = True
        LOG.info("job %s done", job_id)

    except Exception as e:
        if not redact_done and await _requeue_redact_after_transient(
            settings, r, pool, payload, job_id, e
        ):
            return
        await _fail_job(settings, r, pool, payload, job_id, e)
    finally:
        if tmp_path:
            try:
                await asyncio.to_thread(os.unlink, tmp_path)
            except OSError:
                pass


async def dispatch_job(
    settings: Settings,
    pool: AsyncConnectionPool,
    http: httpx.AsyncClient,
    r: redis_async.Redis,
    raw: str,
) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        LOG.error("invalid json: %s", raw[:200])
        return
    job_type = payload.get("type")
    try:
        if job_type == JOB_AUDIO_PROCESS:
            await process_audio_stt(settings, pool, http, r, payload)
        elif job_type == JOB_AUDIO_LLM:
            await process_audio_llm(settings, pool, http, r, payload)
        elif job_type == JOB_AUDIO_REDACT:
            await process_audio_redact(settings, pool, http, r, payload)
        else:
            LOG.warning("unknown type: %s", job_type)
    except Exception:
        LOG.exception("unhandled error for payload")


async def worker_loop(
    settings: Settings,
    pool: AsyncConnectionPool,
    http: httpx.AsyncClient,
    r: redis_async.Redis,
    work_queue: asyncio.Queue[str],
) -> None:
    while True:
        raw = await work_queue.get()
        await dispatch_job(settings, pool, http, r, raw)


async def redis_feeder(
    settings: Settings,
    r: redis_async.Redis,
    work_queue: asyncio.Queue[str],
) -> None:
    while True:
        try:
            item = await r.brpop(settings.queue_key, timeout=settings.brpop_timeout_sec)
        except RedisError as e:
            LOG.warning("redis: %s", e)
            await asyncio.sleep(1)
            continue
        if item is None:
            continue
        _, raw = item
        await work_queue.put(raw)


async def amain() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    _require_worker_urls(settings)
    LOG.info(
        "runner starting (async), queue=%s max_concurrency=%s",
        settings.queue_key,
        settings.max_concurrency,
    )
    if settings.worker_token:
        LOG.info("WORKER_TOKEN задан — к воркерам уйдёт Authorization: Bearer …")
    else:
        LOG.warning(
            "WORKER_TOKEN пуст: запросы к STT/LLM/Redact без Authorization. "
            "Если на воркерах задан WORKER_TOKEN, положите тот же секрет в env runner "
            "(docker-compose: WORKER_TOKEN в .env)."
        )

    work_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_concurrency)
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=settings.max_concurrency + 2,
        open=False,
        kwargs={"autocommit": False},
    )
    await pool.open()

    headers = auth_headers(settings)
    hc = settings.max_concurrency + 10
    limits = httpx.Limits(max_connections=hc, max_keepalive_connections=hc)
    try:
        async with httpx.AsyncClient(headers=headers, limits=limits) as http, redis_async.from_url(
            settings.redis_url, decode_responses=True
        ) as r:
            workers = [
                asyncio.create_task(worker_loop(settings, pool, http, r, work_queue))
                for _ in range(settings.max_concurrency)
            ]
            feeder = asyncio.create_task(redis_feeder(settings, r, work_queue))
            await asyncio.gather(feeder, *workers)
    finally:
        await pool.close()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        LOG.info("runner stopped")


if __name__ == "__main__":
    main()
