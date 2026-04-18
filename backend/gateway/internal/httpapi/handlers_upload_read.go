package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"tulahack/gateway/internal/domain"
	"tulahack/gateway/internal/redisx"
	"tulahack/gateway/internal/store"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"
)

// errRedisUnavailable — ошибка чтения кэша статуса в Redis (не redis.Nil).
var errRedisUnavailable = errors.New("redis unavailable")

func (h *UploadHandlers) RegisterRead(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/uploads", BearerUserID(h.JWT, h.listUploads))
	mux.HandleFunc("GET /api/v1/uploads/{id}", BearerUserID(h.JWT, h.getUpload))
	mux.HandleFunc("GET /api/v1/uploads/{id}/processing-status", BearerUserID(h.JWT, h.processingStatus))
	mux.HandleFunc("GET /api/v1/uploads/{id}/processing-stream", h.processingStatusStream)
}

func (h *UploadHandlers) listUploads(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	uid, ok := UserIDFromContext(r.Context())
	if !ok {
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing user")
		return
	}
	limit := 50
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 100 {
			limit = n
		}
	}
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()

	items, err := store.ListUploadsWithLatestJob(ctx, h.Pool, uid, limit)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not list uploads")
		return
	}
	rows := make([]map[string]any, 0, len(items))
	for _, it := range items {
		rows = append(rows, uploadListItemJSON(it))
	}
	writeJSON(w, http.StatusOK, map[string]any{"uploads": rows})
}

func (h *UploadHandlers) getUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	uid, ok := UserIDFromContext(r.Context())
	if !ok {
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing user")
		return
	}
	raw := r.PathValue("id")
	uploadID, err := uuid.Parse(raw)
	if err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid upload id")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()

	u, err := store.GetAudioUploadByIDAndUser(ctx, h.Pool, uid, uploadID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeAPIError(w, http.StatusNotFound, "not_found", "upload not found")
			return
		}
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load upload")
		return
	}

	job, err := store.ProcessingJobByUpload(ctx, h.Pool, uploadID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, http.StatusOK, map[string]any{
				"upload":         uploadJSON(u),
				"processing_job": nil,
			})
			return
		}
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load processing job")
		return
	}
	if job.UserID != uid {
		writeAPIError(w, http.StatusNotFound, "not_found", "upload not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"upload":         uploadJSON(u),
		"processing_job": processingJobJSON(job),
	})
}

func statusTerminal(s string) bool {
	switch s {
	case domain.JobDone, domain.JobFailed, domain.JobCancelled:
		return true
	default:
		return false
	}
}

// processingStatusBody — то же тело, что у GET …/processing-status (для HTTP и WebSocket).
func (h *UploadHandlers) processingStatusBody(ctx context.Context, uid uuid.UUID, uploadID uuid.UUID) (map[string]any, error) {
	_, err := store.GetAudioUploadByIDAndUser(ctx, h.Pool, uid, uploadID)
	if err != nil {
		return nil, err
	}

	if h.Redis != nil {
		key := redisx.JobStatusCacheKey(uploadID)
		s, err := h.Redis.Get(ctx, key).Result()
		if err == nil && s != "" {
			var m map[string]any
			if json.Unmarshal([]byte(s), &m) == nil {
				st, _ := m["status"].(string)
				out := map[string]any{
					"upload_id":           uploadID.String(),
					"from_cache":          true,
					"status":              st,
					"terminal":            statusTerminal(st),
					"processing_job_id":   m["processing_job_id"],
					"at":                  m["at"],
				}
				if em, ok := m["error_message"].(string); ok && em != "" {
					out["error_message"] = em
				}
				return out, nil
			}
		} else if err != nil && err != redis.Nil {
			return nil, fmt.Errorf("%w: %v", errRedisUnavailable, err)
		}
	}

	jobID, st, err := store.ProcessingJobLatestStatusForUpload(ctx, h.Pool, uid, uploadID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return map[string]any{
				"upload_id":           uploadID.String(),
				"processing_job_id":   nil,
				"status":              "",
				"terminal":            false,
				"from_cache":          false,
				"processing_absent":   true,
			}, nil
		}
		return nil, err
	}

	return map[string]any{
		"upload_id":           uploadID.String(),
		"processing_job_id":   jobID.String(),
		"status":              st,
		"terminal":            statusTerminal(st),
		"from_cache":          false,
	}, nil
}

// processingStatus — лёгкий опрос: сначала Redis (после фиксации транзакции воркером), иначе статус из БД.
func (h *UploadHandlers) processingStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	uid, ok := UserIDFromContext(r.Context())
	if !ok {
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing user")
		return
	}
	raw := r.PathValue("id")
	uploadID, err := uuid.Parse(raw)
	if err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid upload id")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	out, err := h.processingStatusBody(ctx, uid, uploadID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeAPIError(w, http.StatusNotFound, "not_found", "upload not found")
			return
		}
		if errors.Is(err, errRedisUnavailable) {
			writeAPIError(w, http.StatusServiceUnavailable, "redis_error", "redis unavailable")
			return
		}
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load job status")
		return
	}
	writeJSON(w, http.StatusOK, out)
}
