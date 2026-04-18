package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type RefreshToken struct {
	ID        uuid.UUID
	UserID    uuid.UUID
	TokenHash []byte
	ExpiresAt time.Time
}

func InsertRefreshToken(ctx context.Context, pool *pgxpool.Pool, userID uuid.UUID, tokenHash []byte, expiresAt time.Time) (uuid.UUID, error) {
	const q = `
INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
VALUES ($1, $2, $3)
RETURNING id`
	var id uuid.UUID
	err := pool.QueryRow(ctx, q, userID, tokenHash, expiresAt).Scan(&id)
	return id, err
}

func RefreshTokenByHash(ctx context.Context, pool *pgxpool.Pool, tokenHash []byte) (RefreshToken, error) {
	const q = `
SELECT id, user_id, token_hash, expires_at
FROM refresh_tokens WHERE token_hash = $1`
	var t RefreshToken
	err := pool.QueryRow(ctx, q, tokenHash).Scan(
		&t.ID, &t.UserID, &t.TokenHash, &t.ExpiresAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return RefreshToken{}, ErrNotFound
	}
	return t, err
}

func DeleteRefreshToken(ctx context.Context, pool *pgxpool.Pool, id uuid.UUID) error {
	const q = `DELETE FROM refresh_tokens WHERE id = $1`
	tag, err := pool.Exec(ctx, q, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func DeleteRefreshByHash(ctx context.Context, pool *pgxpool.Pool, tokenHash []byte) error {
	_, err := pool.Exec(ctx, `DELETE FROM refresh_tokens WHERE token_hash = $1`, tokenHash)
	return err
}

func RotateRefreshToken(ctx context.Context, pool *pgxpool.Pool, oldID, userID uuid.UUID, newHash []byte, expiresAt time.Time) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `DELETE FROM refresh_tokens WHERE id = $1`, oldID); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `
INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)`,
		userID, newHash, expiresAt,
	); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
