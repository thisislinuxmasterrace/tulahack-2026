package store

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type AudioUpload struct {
	ID               uuid.UUID `json:"id"`
	UserID           uuid.UUID `json:"user_id"`
	Bucket           string    `json:"bucket"`
	ObjectKey        string    `json:"object_key"`
	StorageURL       string    `json:"storage_url"`
	OriginalFilename string    `json:"original_filename"`
	ContentType      string    `json:"content_type"`
	ByteSize         int64     `json:"byte_size"`
	CreatedAt        time.Time `json:"created_at"`
}

// InsertAudioUploadWithProcessingJob атомарно создаёт строку загрузки и задачу обработки.
// Пайплайн на уровне приложения: сначала MinIO, затем эта функция, затем Redis — очередь только после успешного COMMIT.
func InsertAudioUploadWithProcessingJob(
	ctx context.Context,
	pool *pgxpool.Pool,
	userID uuid.UUID,
	bucket, objectKey, storageURL, originalFilename, contentType string,
	byteSize int64,
) (AudioUpload, uuid.UUID, error) {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return AudioUpload{}, uuid.Nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	const qUpload = `
INSERT INTO audio_uploads (user_id, bucket, object_key, storage_url, original_filename, content_type, byte_size)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id, user_id, bucket, object_key, storage_url, original_filename, content_type, byte_size, created_at`
	var u AudioUpload
	if err := tx.QueryRow(ctx, qUpload, userID, bucket, objectKey, storageURL, originalFilename, contentType, byteSize).Scan(
		&u.ID, &u.UserID, &u.Bucket, &u.ObjectKey, &u.StorageURL, &u.OriginalFilename, &u.ContentType, &u.ByteSize, &u.CreatedAt,
	); err != nil {
		return AudioUpload{}, uuid.Nil, err
	}

	const qJob = `
INSERT INTO processing_jobs (upload_id, user_id, status)
VALUES ($1, $2, 'queued')
RETURNING id`
	var jobID uuid.UUID
	if err := tx.QueryRow(ctx, qJob, u.ID, userID).Scan(&jobID); err != nil {
		return AudioUpload{}, uuid.Nil, err
	}

	if err := tx.Commit(ctx); err != nil {
		return AudioUpload{}, uuid.Nil, err
	}
	return u, jobID, nil
}
