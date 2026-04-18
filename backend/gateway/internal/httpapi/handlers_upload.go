package httpapi

import (
	"bytes"
	"context"
	"io"
	"log"
	"mime"
	"net/http"
	"path"
	"strings"
	"time"

	"tulahack/gateway/internal/config"
	"tulahack/gateway/internal/objectstore"
	"tulahack/gateway/internal/redisx"
	"tulahack/gateway/internal/store"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/redis/go-redis/v9"
)

const maxUploadBytes = 50 << 20 // макс. 50 МиБ

var allowedAudioPrefixes = []string{
	"audio/",
	"application/ogg",
	"application/octet-stream", // часто для wav без точного MIME
}

// UploadHandlers — multipart-загрузка аудио в MinIO, Postgres и очередь Redis.
type UploadHandlers struct {
	Pool   *pgxpool.Pool
	Store  *objectstore.Store
	Redis  *redis.Client
	JWT    []byte
}

func (h *UploadHandlers) Register(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/uploads", BearerUserID(h.JWT, h.upload))
	h.RegisterRead(mux)
}

func (h *UploadHandlers) upload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, http.StatusText(http.StatusMethodNotAllowed), http.StatusMethodNotAllowed)
		return
	}
	if h.Pool == nil || h.Store == nil {
		log.Printf("загрузка аудио: ошибка — хранилище или БД не настроены")
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "storage or database not configured")
		return
	}
	publicBase := config.S3PublicBaseURL()
	if publicBase == "" {
		log.Printf("загрузка аудио: ошибка — не задан S3_PUBLIC_BASE_URL")
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "S3_PUBLIC_BASE_URL is not set")
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxUploadBytes+1024)
	if err := r.ParseMultipartForm(maxUploadBytes + 1024); err != nil {
		log.Printf("загрузка аудио: ошибка разбора multipart: %v", err)
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "multipart form: "+err.Error())
		return
	}
	defer func() { _ = r.MultipartForm.RemoveAll() }()

	file, hdr, err := r.FormFile("file")
	if err != nil {
		log.Printf("загрузка аудио: в форме нет поля \"file\"")
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "missing file field \"file\"")
		return
	}
	defer func() { _ = file.Close() }()

	ct := strings.TrimSpace(hdr.Header.Get("Content-Type"))
	if ct == "" {
		ct = mime.TypeByExtension(strings.ToLower(path.Ext(hdr.Filename)))
	}
	if !isAllowedAudio(ct, hdr.Filename) {
		log.Printf("загрузка аудио: отклонён файл \"%s\" (тип %q) — не похоже на аудио", hdr.Filename, ct)
		writeAPIError(w, http.StatusUnprocessableEntity, "validation_error", "file must be an audio type")
		return
	}

	data, err := io.ReadAll(io.LimitReader(file, maxUploadBytes+1))
	if err != nil {
		log.Printf("загрузка аудио: не удалось прочитать тело файла: %v", err)
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "could not read file")
		return
	}
	if int64(len(data)) > maxUploadBytes {
		log.Printf("загрузка аудио: файл слишком большой (%d байт, лимит %d)", len(data), maxUploadBytes)
		writeAPIError(w, http.StatusRequestEntityTooLarge, "payload_too_large", "file too large (max 50 MiB)")
		return
	}

	uid, ok := UserIDFromContext(r.Context())
	if !ok {
		log.Printf("загрузка аудио: внутренняя ошибка — нет user_id в контексте")
		writeAPIError(w, http.StatusUnauthorized, "unauthorized", "missing user")
		return
	}

	log.Printf("загрузка аудио: начало — пользователь %s, файл \"%s\", %d байт, content-type %q",
		uid, hdr.Filename, len(data), ct)

	ext := strings.ToLower(path.Ext(hdr.Filename))
	if ext == "" {
		ext = extFromContentType(ct)
	}
	if ext == "" {
		ext = ".bin"
	}
	objKey := path.Join("uploads", uid.String(), uuid.NewString()+ext)
	objKey = strings.ReplaceAll(objKey, "\\", "/")

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
	defer cancel()

	if strings.TrimSpace(ct) == "" {
		ct = "application/octet-stream"
	}

	// Порядок: MinIO → транзакция БД → LPUSH; при ошибке Redis не ставится.
	_, err = h.Store.Client.PutObject(ctx, h.Store.Bucket, objKey, bytes.NewReader(data), int64(len(data)), minio.PutObjectOptions{
		ContentType: ct,
	})
	if err != nil {
		log.Printf("загрузка аудио: ошибка MinIO (запись объекта): %v", err)
		writeAPIError(w, http.StatusBadGateway, "storage_error", "could not store file: "+err.Error())
		return
	}
	log.Printf("загрузка аудио: файл записан в MinIO — bucket=%s, key=%s", h.Store.Bucket, objKey)

	storageURL := publicBase + "/" + h.Store.Bucket + "/" + objKey
	u, jobID, err := store.InsertAudioUploadWithProcessingJob(ctx, h.Pool, uid, h.Store.Bucket, objKey, storageURL, hdr.Filename, ct, int64(len(data)))
	if err != nil {
		log.Printf("загрузка аудио: ошибка PostgreSQL (метаданные + задача в одной транзакции): %v", err)
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not save metadata")
		return
	}
	log.Printf("загрузка аудио: в БД зафиксированы upload_id=%s и processing_job_id=%s (статус queued)", u.ID, jobID)

	queue := map[string]any{"enqueued": false}
	if h.Redis != nil {
		job := redisx.JobFromUpload(u.ID, uid, jobID, u.Bucket, u.ObjectKey, u.CreatedAt)
		if err := redisx.EnqueueAudioProcess(ctx, h.Redis, job); err != nil {
			log.Printf("загрузка аудио: задача НЕ поставлена в Redis (очередь обработки): %v", err)
			queue["enqueued"] = false
			queue["error"] = err.Error()
		} else {
			qk := redisx.AudioQueueKey()
			log.Printf("загрузка аудио: задача в очереди Redis — ключ %q (воркер сможет забрать audio.process)", qk)
			queue["enqueued"] = true
			queue["queue_key"] = qk
		}
	} else {
		log.Printf("загрузка аудио: Redis не подключён — очередь не используется, обработку нужно запускать вручную")
		queue["reason"] = "redis_disabled"
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"upload": map[string]any{
			"id":                u.ID.String(),
			"bucket":            u.Bucket,
			"object_key":        u.ObjectKey,
			"storage_url":       u.StorageURL,
			"original_filename": u.OriginalFilename,
			"content_type":      u.ContentType,
			"byte_size":         u.ByteSize,
			"created_at":        u.CreatedAt.UTC().Format(time.RFC3339Nano),
		},
		"processing_job": map[string]any{
			"id":     jobID.String(),
			"status": "queued",
		},
		"queue": queue,
	})
	log.Printf("загрузка аудио: готово — HTTP 201, upload_id=%s, processing_job_id=%s", u.ID, jobID)
}

func isAllowedAudio(contentType, filename string) bool {
	ext := strings.ToLower(path.Ext(filename))
	switch ext {
	case ".wav", ".mp3", ".ogg", ".webm", ".m4a", ".flac", ".aac":
		return true
	}
	ct := strings.ToLower(strings.TrimSpace(contentType))
	for _, p := range allowedAudioPrefixes {
		if strings.HasPrefix(ct, p) {
			return true
		}
	}
	if ct == "application/octet-stream" {
		switch ext {
		case ".wav", ".mp3", ".ogg", ".webm", ".m4a", ".flac", ".aac":
			return true
		}
	}
	return false
}

func extFromContentType(ct string) string {
	switch strings.ToLower(ct) {
	case "audio/wav", "audio/x-wav", "audio/wave":
		return ".wav"
	case "audio/mpeg", "audio/mp3":
		return ".mp3"
	case "audio/ogg":
		return ".ogg"
	case "audio/webm":
		return ".webm"
	case "audio/mp4", "audio/x-m4a":
		return ".m4a"
	default:
		return ""
	}
}
