"""
Оркестратор: BRPOP из Redis -> MinIO -> STT (HTTP) -> LLM (HTTP) -> Redact (HTTP) -> MinIO -> PostgreSQL.

Формат задачи совпадает с gateway: type=audio.process, upload_id, user_id,
processing_job_id, bucket, object_key, created_at.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import httpx
import psycopg
import redis
from minio import Minio

LOG = logging.getLogger("runner")

T = TypeVar("T")


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


def http_call_with_retry(
    label: str,
    fn: Callable[[], T],
) -> T:
    """Повторы при сетевых сбоях и 502/503/504; исчерпание — проброс исключения."""
    max_attempts, base = _http_retry_config()
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
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
                time.sleep(delay)
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
                time.sleep(delay)
                continue
            raise
    assert last is not None
    raise last


def _requeue_after_transient(
    settings: Settings,
    r: redis.Redis,
    pg: psycopg.Connection,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    exc: BaseException,
) -> bool:
    """
    Повторная постановка в очередь только если результат STT ещё не зафиксирован в БД.
    Иначе задача остаётся failed — нужен ручной перезапуск пайплайна.
    """
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
        with pg.transaction():
            with pg.cursor() as cur:
                cur.execute(
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
                append_event(
                    cur,
                    job_id,
                    "warning",
                    f"Сетевая ошибка до сохранения STT: {exc!s}; возврат в очередь (попытка {n + 2})",
                )
        raw = json.dumps(new_payload, ensure_ascii=False)
        r.lpush(settings.queue_key, raw)
        set_job_status_cache(r, payload, job_id, "queued")
        LOG.info("job %s requeued (retry_count=%s)", job_id, n + 1)
        return True
    except Exception:
        LOG.exception("requeue failed for job %s", job_id)
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
        llm_timeout_sec=float(os.getenv("LLM_HTTP_TIMEOUT_SEC", "120")),
        redact_timeout_sec=float(os.getenv("REDACT_HTTP_TIMEOUT_SEC", "600")),
        brpop_timeout_sec=int(os.getenv("REDIS_BRPOP_TIMEOUT_SEC", "5")),
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


def append_event(cur: psycopg.Cursor, job_id: uuid.UUID, level: str, message: str) -> None:
    ev = json.dumps(
        [{"ts": datetime.now(timezone.utc).isoformat(), "level": level, "message": message}],
        ensure_ascii=False,
    )
    cur.execute(
        """
        UPDATE processing_jobs
        SET processing_events = coalesce(processing_events, '[]'::jsonb) || %s::jsonb,
            updated_at = now()
        WHERE id = %s
        """,
        (ev, str(job_id)),
    )


def set_job_status(
    cur: psycopg.Cursor,
    job_id: uuid.UUID,
    status: str,
    *,
    stage: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    cur.execute(
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


def run_stt(
    settings: Settings,
    client: httpx.Client,
    file_path: str,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    url = f"{settings.stt_base_url}/v1/transcribe"

    def once() -> dict[str, Any]:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, content_type or "application/octet-stream")}
            r = client.post(
                url,
                files=files,
                headers=auth_headers(settings),
                timeout=settings.stt_timeout_sec,
            )
        r.raise_for_status()
        return r.json()

    return http_call_with_retry("STT", once)


def run_llm(
    settings: Settings,
    client: httpx.Client,
    stt_body: dict[str, Any],
) -> dict[str, Any]:
    url = f"{settings.llm_base_url}/v1/anonymize"
    body = {
        "text": stt_body.get("text") or "",
        "segments": stt_body.get("segments"),
        "language": stt_body.get("language"),
    }

    def once() -> dict[str, Any]:
        r = client.post(
            url,
            json=body,
            headers=auth_headers(settings),
            timeout=settings.llm_timeout_sec,
        )
        r.raise_for_status()
        return r.json()

    return http_call_with_retry("LLM", once)


def run_redact(
    settings: Settings,
    client: httpx.Client,
    file_path: str,
    filename: str,
    content_type: str,
    report_payload: dict[str, Any],
) -> tuple[bytes, str]:
    """Запрос к POST /v1/redact: multipart с полями file и report (JSON с llm_entities / redaction_report)."""
    url = f"{settings.redact_base_url}/v1/redact"

    def once() -> tuple[bytes, str]:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, content_type or "application/octet-stream")}
            data = {"report": json.dumps(report_payload, ensure_ascii=False)}
            r = client.post(
                url,
                files=files,
                data=data,
                headers=auth_headers(settings),
                timeout=settings.redact_timeout_sec,
            )
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
        return r.content, ct

    return http_call_with_retry("redact", once)


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


def set_job_status_cache(
    r: redis.Redis,
    payload: dict[str, Any],
    job_id: uuid.UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Запись в Redis только после успешной фиксации транзакции в Postgres (вызывать снаружи транзакции)."""
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
        r.setex(key, ttl, body_json)
        r.publish(job_events_channel(str(payload["upload_id"])), body_json)
        LOG.info("redis job status: key=%s status=%s", key, status)
    except redis.RedisError as e:
        LOG.warning("redis SET/PUBLISH job status failed: %s", e)


def process_one(
    settings: Settings,
    pg: psycopg.Connection,
    mc: Minio,
    http: httpx.Client,
    r: redis.Redis,
    payload: dict[str, Any],
) -> None:
    job_id = uuid.UUID(payload["processing_job_id"])
    bucket = payload["bucket"]
    object_key = payload["object_key"]

    with pg.transaction():
        with pg.cursor() as cur:
            set_job_status(cur, job_id, "running", stage="download")
            append_event(cur, job_id, "info", "Задача получена из Redis")

    set_job_status_cache(r, payload, job_id, "running")

    ext = os.path.splitext(object_key)[1] or ".wav"
    tmp_path: str | None = None
    stt_persisted = False
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
        mc.fget_object(bucket, object_key, tmp_path)

        orig_name = os.path.basename(object_key)
        content_type = "application/octet-stream"

        with pg.transaction():
            with pg.cursor() as cur:
                set_job_status(cur, job_id, "stt", stage="stt")
                append_event(cur, job_id, "info", "Файл скачан из MinIO, запрос к STT")

        set_job_status_cache(r, payload, job_id, "stt")

        if not settings.stt_base_url:
            raise RuntimeError("STT_BASE_URL is not set")

        stt = run_stt(settings, http, tmp_path, orig_name, content_type)
        whisper_json = whisper_output_from_stt(stt)

        if not settings.llm_base_url:
            raise RuntimeError("LLM_BASE_URL is not set")

        with pg.transaction():
            with pg.cursor() as cur:
                cur.execute(
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
                append_event(cur, job_id, "info", "STT завершён, запрос к LLM")

        set_job_status_cache(r, payload, job_id, "llm")
        stt_persisted = True

        llm = run_llm(settings, http, stt)
        entities = llm.get("llm_entities")
        report = llm.get("redaction_report")

        if not settings.redact_base_url:
            raise RuntimeError("REDACT_BASE_URL is not set")

        with pg.transaction():
            with pg.cursor() as cur:
                cur.execute(
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
                append_event(cur, job_id, "info", "LLM завершён, маскировка аудио (redact)")

        set_job_status_cache(r, payload, job_id, "render_audio")

        report_payload: dict[str, Any] = {
            "llm_entities": entities,
            "redaction_report": report,
        }
        redacted_bytes, redacted_ct = run_redact(
            settings, http, tmp_path, orig_name, content_type, report_payload
        )
        ext_out = os.path.splitext(orig_name)[1] or ".wav"
        redact_key = f"redacted/{payload['upload_id']}/{job_id}{ext_out}"
        mc.put_object(
            settings.s3_bucket,
            redact_key,
            io.BytesIO(redacted_bytes),
            length=len(redacted_bytes),
            content_type=redacted_ct or "application/octet-stream",
        )
        public_base = settings.s3_public_base_url
        if not public_base:
            raise RuntimeError("S3_PUBLIC_BASE_URL is not set (нужен публичный URL для redacted_audio_storage_url)")
        redacted_url = f"{public_base}/{settings.s3_bucket}/{redact_key}"

        with pg.transaction():
            with pg.cursor() as cur:
                cur.execute(
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
                append_event(cur, job_id, "info", "Обработка завершена (redact аудио в MinIO)")

        set_job_status_cache(r, payload, job_id, "done")
        LOG.info("job %s done", job_id)

    except Exception as e:
        if not stt_persisted and _requeue_after_transient(settings, r, pg, payload, job_id, e):
            return
        LOG.exception("job %s failed: %s", job_id, e)
        msg = str(e)[:2000]
        err_code = "network_error" if _is_transient_http_exc(e) else "pipeline_error"
        try:
            with pg.transaction():
                with pg.cursor() as cur:
                    set_job_status(
                        cur,
                        job_id,
                        "failed",
                        stage="failed",
                        error_code=err_code,
                        error_message=msg,
                    )
                    append_event(cur, job_id, "error", msg)
                    cur.execute(
                        "UPDATE processing_jobs SET finished_at = now(), updated_at = now() WHERE id = %s",
                        (str(job_id),),
                    )
        except Exception:
            LOG.exception("could not persist failed status for job %s", job_id)
        else:
            set_job_status_cache(r, payload, job_id, "failed", error_message=msg)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    _require_worker_urls(settings)
    LOG.info("runner starting, queue=%s", settings.queue_key)

    r = redis.from_url(settings.redis_url, decode_responses=True)
    mc = minio_client(settings)
    with psycopg.connect(settings.database_url) as pg, httpx.Client() as http:
        while True:
            try:
                item = r.brpop(settings.queue_key, timeout=settings.brpop_timeout_sec)
            except redis.RedisError as e:
                LOG.warning("redis: %s", e)
                time.sleep(1)
                continue

            if item is None:
                continue

            _, raw = item
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                LOG.error("invalid json: %s", raw[:200])
                continue

            if payload.get("type") != "audio.process":
                LOG.warning("unknown type: %s", payload.get("type"))
                continue

            try:
                process_one(settings, pg, mc, http, r, payload)
            except Exception:
                LOG.exception("unhandled error for payload")


if __name__ == "__main__":
    main()
