package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"sync"
	"time"

	"tulahack/gateway/internal/auth"
	"tulahack/gateway/internal/redisx"
	"tulahack/gateway/internal/store"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
)

var processingStreamUpgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 4096,
	CheckOrigin: func(r *http.Request) bool { return true },
}

// processingStatusStream — WebSocket: первый кадр — снимок как у GET …/processing-status, далее Pub/Sub из Redis.
func (h *UploadHandlers) processingStatusStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	if h.Redis == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "redis not configured")
		return
	}
	token := BearerTokenFromRequest(r)
	if token == "" {
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing access token")
		return
	}
	uid, err := auth.ParseAccess(h.JWT, token)
	if err != nil {
		if errors.Is(err, jwt.ErrTokenExpired) {
			writeAPIError(w, http.StatusUnauthorized, "token_expired", "access token expired")
			return
		}
		writeAPIError(w, http.StatusUnauthorized, "invalid_token", "invalid access token")
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

	snap, err := h.processingStatusBody(ctx, uid, uploadID)
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

	conn, err := processingStreamUpgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer conn.Close()

	var writeMu sync.Mutex
	writeWS := func(payload map[string]any) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteJSON(payload)
	}
	if err := writeWS(snap); err != nil {
		return
	}
	if term, _ := snap["terminal"].(bool); term {
		return
	}

	runCtx, runCancel := context.WithCancel(r.Context())
	defer runCancel()

	go func() {
		defer runCancel()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}()

	pubsub := h.Redis.Subscribe(runCtx, redisx.JobEventsChannel(uploadID))
	defer pubsub.Close()
	ch := pubsub.Channel()

	for {
		select {
		case <-runCtx.Done():
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			if msg == nil {
				return
			}
			var m map[string]any
			if json.Unmarshal([]byte(msg.Payload), &m) != nil {
				continue
			}
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
			if err := writeWS(out); err != nil {
				return
			}
			if statusTerminal(st) {
				return
			}
		}
	}
}
