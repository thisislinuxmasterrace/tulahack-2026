package db

import (
	"context"
	"os"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
)

// PoolFromEnv — пул подключений при заданном DATABASE_URL, иначе nil.
func PoolFromEnv(ctx context.Context) (*pgxpool.Pool, error) {
	dsn := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if dsn == "" {
		return nil, nil
	}
	return pgxpool.New(ctx, dsn)
}

// PingStatus — краткая строка для JSON health: "disabled", "ok" или "error: …".
func PingStatus(ctx context.Context, pool *pgxpool.Pool) string {
	if pool == nil {
		return "disabled"
	}
	if err := pool.Ping(ctx); err != nil {
		return "error: " + err.Error()
	}
	return "ok"
}
