package store

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// UploadListItem — одна строка списка: загрузка + последняя задача обработки (если есть).
type UploadListItem struct {
	Upload       AudioUpload
	JobID        *uuid.UUID
	JobStatus    *string
	JobUpdatedAt *time.Time
}

// ListUploadsWithLatestJob возвращает загрузки пользователя с последней задачей по каждой (по created_at).
func ListUploadsWithLatestJob(ctx context.Context, pool *pgxpool.Pool, userID uuid.UUID, limit int) ([]UploadListItem, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	const q = `
SELECT
  u.id, u.user_id, u.bucket, u.object_key, u.storage_url, u.original_filename, u.content_type, u.byte_size, u.created_at,
  j.id::text, j.status, j.updated_at
FROM audio_uploads u
LEFT JOIN LATERAL (
  SELECT id, status, updated_at
  FROM processing_jobs
  WHERE upload_id = u.id
  ORDER BY created_at DESC
  LIMIT 1
) j ON true
WHERE u.user_id = $1
ORDER BY u.created_at DESC
LIMIT $2`
	rows, err := pool.Query(ctx, q, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []UploadListItem
	for rows.Next() {
		var u AudioUpload
		var jobIDStr sql.NullString
		var jobStatus sql.NullString
		var jobUpdated sql.NullTime
		if err := rows.Scan(
			&u.ID, &u.UserID, &u.Bucket, &u.ObjectKey, &u.StorageURL, &u.OriginalFilename, &u.ContentType, &u.ByteSize, &u.CreatedAt,
			&jobIDStr, &jobStatus, &jobUpdated,
		); err != nil {
			return nil, err
		}
		item := UploadListItem{Upload: u}
		if jobIDStr.Valid && jobIDStr.String != "" {
			id, err := uuid.Parse(jobIDStr.String)
			if err == nil {
				item.JobID = &id
			}
		}
		if jobStatus.Valid {
			s := jobStatus.String
			item.JobStatus = &s
		}
		if jobUpdated.Valid {
			t := jobUpdated.Time
			item.JobUpdatedAt = &t
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

// GetAudioUploadByIDAndUser возвращает загрузку, если она принадлежит пользователю.
func GetAudioUploadByIDAndUser(ctx context.Context, pool *pgxpool.Pool, userID, uploadID uuid.UUID) (AudioUpload, error) {
	const q = `
SELECT id, user_id, bucket, object_key, storage_url, original_filename, content_type, byte_size, created_at
FROM audio_uploads
WHERE id = $1 AND user_id = $2`
	var u AudioUpload
	err := pool.QueryRow(ctx, q, uploadID, userID).Scan(
		&u.ID, &u.UserID, &u.Bucket, &u.ObjectKey, &u.StorageURL, &u.OriginalFilename, &u.ContentType, &u.ByteSize, &u.CreatedAt,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return AudioUpload{}, ErrNotFound
		}
		return AudioUpload{}, err
	}
	return u, nil
}
