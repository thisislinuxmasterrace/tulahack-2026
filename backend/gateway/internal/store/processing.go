package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ProcessingJob строка таблицы processing_jobs (поля JSON — сырые json.RawMessage / скан в map при необходимости).
type ProcessingJob struct {
	ID                       uuid.UUID
	UploadID                 uuid.UUID
	UserID                   uuid.UUID
	Status                   string
	Stage                    *string
	ErrorCode                *string
	ErrorMessage             *string
	WhisperModel             *string
	LlmModel                 *string
	WhisperOutput            []byte
	LlmEntities              []byte
	TranscriptPlain          *string
	TranscriptRedacted       *string
	RedactionReport          []byte
	RedactedAudioBucket      *string
	RedactedAudioObjectKey   *string
	RedactedAudioStorageURL  *string
	ProcessingEvents         []byte
	StartedAt                *time.Time
	FinishedAt               *time.Time
	CreatedAt                time.Time
	UpdatedAt                time.Time
}

// ProcessingJobByUpload возвращает последнюю задачу по upload_id.
func ProcessingJobByUpload(ctx context.Context, pool *pgxpool.Pool, uploadID uuid.UUID) (ProcessingJob, error) {
	const q = `
SELECT id, upload_id, user_id, status, stage, error_code, error_message,
       whisper_model, llm_model,
       whisper_output, llm_entities, transcript_plain, transcript_redacted, redaction_report,
       redacted_audio_bucket, redacted_audio_object_key, redacted_audio_storage_url,
       processing_events, started_at, finished_at, created_at, updated_at
FROM processing_jobs
WHERE upload_id = $1
ORDER BY created_at DESC
LIMIT 1`
	return scanProcessingJob(pool.QueryRow(ctx, q, uploadID))
}

// ProcessingJobLatestStatusForUpload возвращает id и status последней задачи по upload_id при совпадении user_id.
func ProcessingJobLatestStatusForUpload(ctx context.Context, pool *pgxpool.Pool, userID, uploadID uuid.UUID) (jobID uuid.UUID, status string, err error) {
	const q = `
SELECT j.id, j.status
FROM processing_jobs j
INNER JOIN audio_uploads u ON u.id = j.upload_id
WHERE j.upload_id = $1 AND u.user_id = $2
ORDER BY j.created_at DESC
LIMIT 1`
	err = pool.QueryRow(ctx, q, uploadID, userID).Scan(&jobID, &status)
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, "", ErrNotFound
	}
	return jobID, status, err
}

func scanProcessingJob(row interface {
	Scan(dest ...any) error
}) (ProcessingJob, error) {
	var j ProcessingJob
	var whisper, llm, report, events []byte
	err := row.Scan(
		&j.ID, &j.UploadID, &j.UserID, &j.Status, &j.Stage, &j.ErrorCode, &j.ErrorMessage,
		&j.WhisperModel, &j.LlmModel,
		&whisper, &llm, &j.TranscriptPlain, &j.TranscriptRedacted, &report,
		&j.RedactedAudioBucket, &j.RedactedAudioObjectKey, &j.RedactedAudioStorageURL,
		&events, &j.StartedAt, &j.FinishedAt, &j.CreatedAt, &j.UpdatedAt,
	)
	j.WhisperOutput = whisper
	j.LlmEntities = llm
	j.RedactionReport = report
	j.ProcessingEvents = events
	return j, err
}

// AppendProcessingEvent добавляет элемент в processing_events (массив JSON).
func AppendProcessingEvent(ctx context.Context, pool *pgxpool.Pool, jobID uuid.UUID, ev map[string]any) error {
	chunk, err := json.Marshal([]any{ev})
	if err != nil {
		return err
	}
	const q = `
UPDATE processing_jobs
SET processing_events = coalesce(processing_events, '[]'::jsonb) || $2::jsonb,
    updated_at = now()
WHERE id = $1`
	_, err = pool.Exec(ctx, q, jobID, chunk)
	return err
}
