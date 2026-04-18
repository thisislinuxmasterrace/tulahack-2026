package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"tulahack/gateway/internal/config"
	"tulahack/gateway/internal/db"
	"tulahack/gateway/internal/httpapi"
	"tulahack/gateway/internal/migrate"
	"tulahack/gateway/internal/objectstore"
	"tulahack/gateway/internal/redisx"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.SetPrefix("gateway | ")

	addr := ":8080"
	if v := os.Getenv("GATEWAY_ADDR"); v != "" {
		addr = v
	}

	ctx := context.Background()
	pool, err := db.PoolFromEnv(ctx)
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	if pool != nil {
		if err := pool.Ping(ctx); err != nil {
			log.Fatalf("database ping: %v", err)
		}
		log.Printf("database: connected")
		if err := migrate.Up(ctx, pool); err != nil {
			log.Fatalf("database schema: %v", err)
		}
	} else {
		log.Printf("database: DATABASE_URL not set, skipping")
	}

	rdb, err := redisx.ClientFromEnv()
	if err != nil {
		log.Fatalf("redis: %v", err)
	}
	if rdb != nil {
		if err := rdb.Ping(ctx).Err(); err != nil {
			log.Fatalf("redis ping: %v", err)
		}
		log.Printf("redis: connected")
	} else {
		log.Printf("redis: REDIS_URL not set, skipping")
	}

	store, err := objectstore.FromEnv(ctx)
	if err != nil {
		log.Fatalf("object storage: %v", err)
	}
	if store != nil {
		log.Printf("object storage: connected (bucket=%s)", store.Bucket)
	} else {
		log.Printf("object storage: S3_ENDPOINT not set, skipping")
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		handleHealth(w, r, pool, rdb, store)
	})
	mux.HandleFunc("GET /api/v1/health", func(w http.ResponseWriter, r *http.Request) {
		handleHealthV1(w, r, pool, rdb, store)
	})

	if pool != nil {
		authCfg, err := config.AuthFromEnv()
		if err != nil {
			log.Fatalf("auth config: %v", err)
		}
		(&httpapi.AuthHandlers{Pool: pool, Cfg: authCfg}).Register(mux)
		(&httpapi.UploadHandlers{Pool: pool, Store: store, Redis: rdb, JWT: authCfg.JWTSecret}).Register(mux)
	}

	logStartupSummary(addr, pool, rdb, store)

	shutdownTimeout := shutdownTimeoutFromEnv()

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 15 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Printf("gateway listening on %s", addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

	sigCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	select {
	case err := <-errCh:
		log.Fatalf("listen: %v", err)
	case <-sigCtx.Done():
		log.Printf("shutdown: signal received, draining (timeout %s)", shutdownTimeout)
	}

	shutCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		log.Printf("shutdown: http: %v", err)
	} else {
		log.Printf("shutdown: http server stopped")
	}

	if pool != nil {
		pool.Close()
		log.Printf("shutdown: database pool closed")
	}
	if rdb != nil {
		if err := rdb.Close(); err != nil {
			log.Printf("shutdown: redis close: %v", err)
		} else {
			log.Printf("shutdown: redis closed")
		}
	}
	log.Printf("shutdown: complete")
}

func logStartupSummary(addr string, pool *pgxpool.Pool, rdb *redis.Client, store *objectstore.Store) {
	log.Printf("startup: listen=%s postgres=%v redis=%v object_storage=%v auth_routes=%v",
		addr, pool != nil, rdb != nil, store != nil, pool != nil)
	if rdb != nil {
		log.Printf("startup: redis_audio_queue=%s", redisx.AudioQueueKey())
	}
	if store != nil {
		log.Printf("startup: s3_bucket=%s", store.Bucket)
	}
	if gatewayLogVerbose() {
		log.Printf("startup: S3_PUBLIC_BASE_URL=%q", os.Getenv("S3_PUBLIC_BASE_URL"))
		log.Printf("startup: SHUTDOWN_TIMEOUT_SEC=%q", strings.TrimSpace(os.Getenv("SHUTDOWN_TIMEOUT_SEC")))
	}
}

func gatewayLogVerbose() bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv("GATEWAY_LOG_VERBOSE")))
	return v == "1" || v == "true" || v == "yes"
}

func shutdownTimeoutFromEnv() time.Duration {
	const def = 30 * time.Second
	v := strings.TrimSpace(os.Getenv("SHUTDOWN_TIMEOUT_SEC"))
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n <= 0 || n > 600 {
		return def
	}
	return time.Duration(n) * time.Second
}

func handleHealth(w http.ResponseWriter, r *http.Request, pool *pgxpool.Pool, rdb *redis.Client, store *objectstore.Store) {
	w.Header().Set("Content-Type", "application/json")
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	dbStatus := db.PingStatus(ctx, pool)
	redisStatus := redisx.PingStatus(ctx, rdb)
	s3Status := objectstore.PingStatus(ctx, store)
	out := map[string]string{
		"status":    "ok",
		"service":   "gateway",
		"database":  dbStatus,
		"redis":     redisStatus,
		"s3":        s3Status,
	}
	if gatewayDegraded(pool, rdb, store, dbStatus, redisStatus, s3Status) {
		out["status"] = "degraded"
		w.WriteHeader(http.StatusServiceUnavailable)
	}
	_ = json.NewEncoder(w).Encode(out)
}

func gatewayDegraded(pool *pgxpool.Pool, rdb *redis.Client, store *objectstore.Store, dbStatus, redisStatus, s3Status string) bool {
	if pool != nil && dbStatus != "ok" {
		return true
	}
	if rdb != nil && redisStatus != "ok" {
		return true
	}
	if store != nil && s3Status != "ok" {
		return true
	}
	return false
}

// handleHealthV1 — JSON со статусом шлюза, PostgreSQL, Redis и S3 (MinIO).
func handleHealthV1(w http.ResponseWriter, r *http.Request, pool *pgxpool.Pool, rdb *redis.Client, store *objectstore.Store) {
	w.Header().Set("Content-Type", "application/json")

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	dbStatus := db.PingStatus(ctx, pool)
	redisStatus := redisx.PingStatus(ctx, rdb)
	s3Status := objectstore.PingStatus(ctx, store)
	gw := map[string]string{
		"status":   "ok",
		"service":  "gateway",
		"database": dbStatus,
		"redis":    redisStatus,
		"s3":       s3Status,
	}
	if gatewayDegraded(pool, rdb, store, dbStatus, redisStatus, s3Status) {
		gw["status"] = "degraded"
	}

	code := http.StatusOK
	if gw["status"] == "degraded" {
		code = http.StatusServiceUnavailable
	}
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]any{"gateway": gw})
}
