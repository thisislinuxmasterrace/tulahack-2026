package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"tulahack/gateway/internal/auth"
	"tulahack/gateway/internal/config"
	"tulahack/gateway/internal/store"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type AuthHandlers struct {
	Pool *pgxpool.Pool
	Cfg  config.Auth
}

func (h *AuthHandlers) Register(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/auth/register", h.register)
	mux.HandleFunc("POST /api/v1/auth/login", h.login)
	mux.HandleFunc("POST /api/v1/auth/refresh", h.refresh)
	mux.HandleFunc("POST /api/v1/auth/logout", h.logout)
	mux.HandleFunc("GET /api/v1/me", BearerUserID(h.Cfg.JWTSecret, h.me))
}

func (h *AuthHandlers) register(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid JSON body")
		return
	}
	if msg := validateUsername(body.Username); msg != "" {
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", msg)
		return
	}
	if msg := validatePassword(body.Password); msg != "" {
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", msg)
		return
	}
	hash, err := auth.HashPassword(body.Password)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not hash password")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	u, err := store.CreateUser(ctx, h.Pool, body.Username, hash)
	if errors.Is(err, store.ErrConflict) {
		writeAPIError(w, http.StatusConflict, "username_taken", "username already exists")
		return
	}
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not create user")
		return
	}
	resp, err := h.issueTokens(ctx, u.ID, u.Username, u.CreatedAt)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not issue tokens")
		return
	}
	writeJSON(w, http.StatusCreated, resp)
}

func (h *AuthHandlers) login(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid JSON body")
		return
	}
	username := body.Username
	if msg := validateUsername(username); msg != "" {
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", msg)
		return
	}
	if body.Password == "" {
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", "password is required")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	u, err := store.UserByUsername(ctx, h.Pool, username)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeAPIError(w, http.StatusUnauthorized, "invalid_credentials", "invalid username or password")
			return
		}
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load user")
		return
	}
	if !auth.PasswordMatches(u.PasswordHash, body.Password) {
		writeAPIError(w, http.StatusUnauthorized, "invalid_credentials", "invalid username or password")
		return
	}
	resp, err := h.issueTokens(ctx, u.ID, u.Username, u.CreatedAt)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not issue tokens")
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *AuthHandlers) refresh(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var body struct {
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid JSON body")
		return
	}
	if body.RefreshToken == "" {
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", "refresh_token is required")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	hash := auth.HashRefresh(body.RefreshToken)
	row, err := store.RefreshTokenByHash(ctx, h.Pool, hash)
	if errors.Is(err, store.ErrNotFound) {
		writeAPIError(w, http.StatusUnauthorized, "invalid_refresh_token", "refresh token not found")
		return
	}
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not validate refresh token")
		return
	}
	if time.Now().After(row.ExpiresAt) {
		_ = store.DeleteRefreshToken(ctx, h.Pool, row.ID)
		writeAPIError(w, http.StatusUnauthorized, "invalid_refresh_token", "refresh token expired")
		return
	}

	u, err := store.UserByID(ctx, h.Pool, row.UserID)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load user")
		return
	}

	raw, newHash, err := auth.NewRefreshToken()
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not generate token")
		return
	}
	expiresAt := time.Now().Add(h.Cfg.RefreshTTL)
	if err := store.RotateRefreshToken(ctx, h.Pool, row.ID, row.UserID, newHash, expiresAt); err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not rotate refresh token")
		return
	}

	access, err := auth.IssueAccess(h.Cfg.JWTSecret, u.ID, h.Cfg.AccessTTL)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not issue access token")
		return
	}
	writeJSON(w, http.StatusOK, tokenResponse(access, raw, u.ID, u.Username, u.CreatedAt, h.Cfg.AccessTTL))
}

func (h *AuthHandlers) logout(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "database not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var body struct {
		RefreshToken string `json:"refresh_token"`
	}
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(&body); err != nil && !errors.Is(err, io.EOF) {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "invalid JSON body")
		return
	}
	if body.RefreshToken != "" {
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		hash := auth.HashRefresh(body.RefreshToken)
		_ = store.DeleteRefreshByHash(ctx, h.Pool, hash)
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *AuthHandlers) me(w http.ResponseWriter, r *http.Request) {
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
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing user context")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	u, err := store.UserByID(ctx, h.Pool, uid)
	if errors.Is(err, store.ErrNotFound) {
		writeAPIError(w, http.StatusUnauthorized, "invalid_token", "user not found")
		return
	}
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load user")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"user": userJSON(u.ID, u.Username, u.CreatedAt)})
}

func (h *AuthHandlers) issueTokens(ctx context.Context, id uuid.UUID, username string, createdAt time.Time) (map[string]any, error) {
	raw, hash, err := auth.NewRefreshToken()
	if err != nil {
		return nil, err
	}
	expiresAt := time.Now().Add(h.Cfg.RefreshTTL)
	if _, err := store.InsertRefreshToken(ctx, h.Pool, id, hash, expiresAt); err != nil {
		return nil, err
	}
	access, err := auth.IssueAccess(h.Cfg.JWTSecret, id, h.Cfg.AccessTTL)
	if err != nil {
		return nil, err
	}
	return tokenResponse(access, raw, id, username, createdAt, h.Cfg.AccessTTL), nil
}

func tokenResponse(access, refresh string, id uuid.UUID, username string, createdAt time.Time, accessTTL time.Duration) map[string]any {
	return map[string]any{
		"token_type":    "Bearer",
		"expires_in":    int(accessTTL.Seconds()),
		"access_token":  access,
		"refresh_token": refresh,
		"user":          userJSON(id, username, createdAt),
	}
}

func userJSON(id uuid.UUID, username string, createdAt time.Time) map[string]any {
	return map[string]any{
		"id":         id.String(),
		"username":   username,
		"created_at": createdAt.UTC().Format(time.RFC3339Nano),
	}
}
