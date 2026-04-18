package httpapi

import (
	"errors"
	"log"
	"net/http"
	"strings"

	"tulahack/gateway/internal/auth"

	"github.com/golang-jwt/jwt/v5"
)

// BearerTokenFromRequest — заголовок Authorization: Bearer … или query access_token (для WebSocket в браузере).
func BearerTokenFromRequest(r *http.Request) string {
	raw := strings.TrimSpace(r.Header.Get("Authorization"))
	const prefix = "Bearer "
	if strings.HasPrefix(raw, prefix) {
		return strings.TrimSpace(strings.TrimPrefix(raw, prefix))
	}
	return strings.TrimSpace(r.URL.Query().Get("access_token"))
}

func logUploadAuthFail(r *http.Request, reason string) {
	if r.URL.Path != "/api/v1/uploads" || r.Method != http.MethodPost {
		return
	}
	log.Printf("загрузка аудио: отказ — %s", reason)
}

// BearerUserIDHeaderOrQuery — JWT из Authorization: Bearer … или из query access_token (как у WebSocket).
// Удобно для <audio src> и ссылок «Скачать», где нельзя задать заголовок.
func BearerUserIDHeaderOrQuery(secret []byte, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := BearerTokenFromRequest(r)
		if token == "" {
			writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing access token (Authorization Bearer or access_token query)")
			return
		}
		uid, err := auth.ParseAccess(secret, token)
		if err != nil {
			if errors.Is(err, jwt.ErrTokenExpired) {
				writeAPIError(w, http.StatusUnauthorized, "token_expired", "access token expired")
				return
			}
			writeAPIError(w, http.StatusUnauthorized, "invalid_token", "invalid access token")
			return
		}
		next(w, r.WithContext(WithUserID(r.Context(), uid)))
	}
}

func BearerUserID(secret []byte, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		raw := strings.TrimSpace(r.Header.Get("Authorization"))
		if raw == "" {
			logUploadAuthFail(r, "нет заголовка Authorization (нужен Bearer-токен после входа)")
			writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing Authorization header")
			return
		}
		const prefix = "Bearer "
		if !strings.HasPrefix(raw, prefix) {
			logUploadAuthFail(r, "заголовок Authorization должен начинаться с \"Bearer \"")
			writeAPIError(w, http.StatusUnauthorized, "unauthorized", "Authorization must be Bearer token")
			return
		}
		token := strings.TrimSpace(strings.TrimPrefix(raw, prefix))
		if token == "" {
			logUploadAuthFail(r, "пустой токен после Bearer")
			writeAPIError(w, http.StatusUnauthorized, "unauthorized", "empty bearer token")
			return
		}
		uid, err := auth.ParseAccess(secret, token)
		if err != nil {
			if errors.Is(err, jwt.ErrTokenExpired) {
				logUploadAuthFail(r, "срок действия access-токена истёк, войдите снова")
				writeAPIError(w, http.StatusUnauthorized, "token_expired", "access token expired")
				return
			}
			logUploadAuthFail(r, "недействительный access-токен")
			writeAPIError(w, http.StatusUnauthorized, "invalid_token", "invalid access token")
			return
		}
		next(w, r.WithContext(WithUserID(r.Context(), uid)))
	}
}
