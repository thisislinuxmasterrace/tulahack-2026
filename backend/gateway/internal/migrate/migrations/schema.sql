-- Полная схема БД при первом запуске (без истории миграций).

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_username_len CHECK (char_length(username) >= 3 AND char_length(username) <= 32)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE TABLE IF NOT EXISTS audio_uploads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    bucket text NOT NULL,
    object_key text NOT NULL,
    storage_url text NOT NULL,
    original_filename text NOT NULL,
    content_type text NOT NULL DEFAULT '',
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audio_uploads_user_id ON audio_uploads (user_id);
CREATE INDEX IF NOT EXISTS idx_audio_uploads_created_at ON audio_uploads (created_at DESC);

-- Пайплайн: Whisper (STT) → Llama (сущности ПДн) → при необходимости рендер аудио.

CREATE TABLE IF NOT EXISTS processing_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    upload_id uuid NOT NULL REFERENCES audio_uploads (id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,

    status text NOT NULL DEFAULT 'queued'
        CONSTRAINT processing_jobs_status_check CHECK (
            status IN (
                'queued',
                'running',
                'stt',
                'llm',
                'render_audio',
                'done',
                'failed',
                'cancelled'
            )
        ),

    stage text,

    error_code text,
    error_message text,

    whisper_model text,
    llm_model text,

    whisper_output jsonb,
    llm_entities jsonb,

    transcript_plain text,
    transcript_redacted text,

    redaction_report jsonb,

    redacted_audio_bucket text,
    redacted_audio_object_key text,
    redacted_audio_storage_url text,

    processing_events jsonb,

    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_user_created ON processing_jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_upload_id ON processing_jobs (upload_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_llm_entities_gin ON processing_jobs USING gin (llm_entities jsonb_path_ops);

COMMENT ON TABLE processing_jobs IS 'Одна задача обработки на загрузку (или повторный прогон); метаданные STT/LLM и ссылки на артефакты в S3.';
COMMENT ON COLUMN processing_jobs.whisper_output IS 'JSON: язык, длительность, segments[], words[] с таймкодами.';
COMMENT ON COLUMN processing_jobs.llm_entities IS 'JSON: массив сущностей ПДн с типом и позициями в тексте/времени.';
COMMENT ON COLUMN processing_jobs.redaction_report IS 'JSON: счётчики по типам ПДн и spans для подсветки в UI.';
