package redisx

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// DefaultAudioQueueKey — значение, если REDIS_AUDIO_QUEUE_KEY пуст.
const DefaultAudioQueueKey = "tulahack:queue:audio:process"

// AudioProcessJob — одна JSON-строка в списке Redis (LPUSH).
type AudioProcessJob struct {
	Type              string    `json:"type"`
	UploadID          string    `json:"upload_id"`
	UserID            string    `json:"user_id"`
	ProcessingJobID   string    `json:"processing_job_id,omitempty"`
	Bucket            string    `json:"bucket"`
	ObjectKey         string    `json:"object_key"`
	CreatedAt         time.Time `json:"created_at"`
}

// AudioQueueKey — ключ списка Redis для задач обработки аудио.
func AudioQueueKey() string {
	v := strings.TrimSpace(os.Getenv("REDIS_AUDIO_QUEUE_KEY"))
	if v == "" {
		return DefaultAudioQueueKey
	}
	return v
}

// EnqueueAudioProcess выполняет LPUSH с JSON-телом; c не должен быть nil.
func EnqueueAudioProcess(ctx context.Context, c *redis.Client, job AudioProcessJob) error {
	if c == nil {
		return errors.New("redis client is nil")
	}
	job.Type = "audio.process"
	payload, err := json.Marshal(job)
	if err != nil {
		return err
	}
	return c.LPush(ctx, AudioQueueKey(), string(payload)).Err()
}

// JobFromUpload собирает задачу после сохранения строки загрузки в БД.
func JobFromUpload(uploadID, userID uuid.UUID, processingJobID uuid.UUID, bucket, objectKey string, createdAt time.Time) AudioProcessJob {
	return AudioProcessJob{
		Type:            "audio.process",
		UploadID:        uploadID.String(),
		UserID:          userID.String(),
		ProcessingJobID: processingJobID.String(),
		Bucket:          bucket,
		ObjectKey:       objectKey,
		CreatedAt:       createdAt.UTC(),
	}
}
