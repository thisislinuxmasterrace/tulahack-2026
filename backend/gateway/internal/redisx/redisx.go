package redisx

import (
	"context"
	"os"
	"strings"

	"github.com/redis/go-redis/v9"
)

// ClientFromEnv — клиент Redis при заданном REDIS_URL, иначе nil.
func ClientFromEnv() (*redis.Client, error) {
	raw := strings.TrimSpace(os.Getenv("REDIS_URL"))
	if raw == "" {
		return nil, nil
	}
	opt, err := redis.ParseURL(raw)
	if err != nil {
		return nil, err
	}
	return redis.NewClient(opt), nil
}

// PingStatus — для health: "disabled", "ok" или "error: …".
func PingStatus(ctx context.Context, c *redis.Client) string {
	if c == nil {
		return "disabled"
	}
	if err := c.Ping(ctx).Err(); err != nil {
		return "error: " + err.Error()
	}
	return "ok"
}
