package migrate

import (
	"context"
	_ "embed"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/schema.sql
var schemaSQL string

// Up применяет полную схему БД (первый запуск, без отдельных миграций).
func Up(ctx context.Context, pool *pgxpool.Pool) error {
	if _, err := pool.Exec(ctx, schemaSQL); err != nil {
		return fmt.Errorf("schema.sql: %w", err)
	}
	return nil
}
