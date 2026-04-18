package redisx

import (
	"os"
	"strings"

	"github.com/google/uuid"
)

// JobStatusCacheKey — ключ для снимка статуса задачи после фиксации транзакции в Postgres (совпадает с workers/runner).
func JobStatusCacheKey(uploadID uuid.UUID) string {
	prefix := strings.TrimSpace(os.Getenv("REDIS_JOB_STATUS_KEY_PREFIX"))
	if prefix == "" {
		prefix = "tulahack:job:status:"
	}
	if !strings.HasSuffix(prefix, ":") {
		prefix += ":"
	}
	return prefix + uploadID.String()
}

// JobEventsChannel — канал Pub/Sub для push-уведомлений о смене статуса (тот же JSON, что в SET ключа).
func JobEventsChannel(uploadID uuid.UUID) string {
	prefix := strings.TrimSpace(os.Getenv("REDIS_JOB_EVENTS_CHANNEL_PREFIX"))
	if prefix == "" {
		prefix = "tulahack:job:events:"
	}
	if !strings.HasSuffix(prefix, ":") {
		prefix += ":"
	}
	return prefix + uploadID.String()
}
