package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type User struct {
	ID           uuid.UUID
	Username     string
	PasswordHash string
	CreatedAt    time.Time
}

func CreateUser(ctx context.Context, pool *pgxpool.Pool, username, passwordHash string) (User, error) {
	const q = `
INSERT INTO users (username, password_hash)
VALUES ($1, $2)
RETURNING id, username, password_hash, created_at`
	var u User
	err := pool.QueryRow(ctx, q, username, passwordHash).Scan(
		&u.ID, &u.Username, &u.PasswordHash, &u.CreatedAt,
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			return User{}, ErrConflict
		}
		return User{}, err
	}
	return u, nil
}

var ErrConflict = errors.New("conflict")

func UserByUsername(ctx context.Context, pool *pgxpool.Pool, username string) (User, error) {
	const q = `
SELECT id, username, password_hash, created_at
FROM users WHERE username = $1`
	var u User
	err := pool.QueryRow(ctx, q, username).Scan(
		&u.ID, &u.Username, &u.PasswordHash, &u.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return User{}, ErrNotFound
	}
	return u, err
}

func UserByID(ctx context.Context, pool *pgxpool.Pool, id uuid.UUID) (User, error) {
	const q = `
SELECT id, username, password_hash, created_at
FROM users WHERE id = $1`
	var u User
	err := pool.QueryRow(ctx, q, id).Scan(
		&u.ID, &u.Username, &u.PasswordHash, &u.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return User{}, ErrNotFound
	}
	return u, err
}
