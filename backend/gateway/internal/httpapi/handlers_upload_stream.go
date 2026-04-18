package httpapi

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"path"
	"strings"
	"time"

	"tulahack/gateway/internal/store"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/minio/minio-go/v7"
)

func (h *UploadHandlers) RegisterStreamRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/uploads/{id}/original", BearerUserIDHeaderOrQuery(h.JWT, h.streamUploadOriginal))
	mux.HandleFunc("GET /api/v1/uploads/{id}/redacted-audio", BearerUserIDHeaderOrQuery(h.JWT, h.streamUploadRedacted))
}

func contentDispositionInlineOrAttachment(attachment bool, filename string) string {
	base := path.Base(strings.TrimSpace(filename))
	if base == "" || base == "." || base == "/" {
		base = "audio"
	}
	safe := strings.Map(func(r rune) rune {
		if r < 32 || r > 126 || strings.ContainsRune(`"%\`, r) {
			return '_'
		}
		return r
	}, base)
	kind := "inline"
	if attachment {
		kind = "attachment"
	}
	return fmt.Sprintf(`%s; filename="%s"`, kind, safe)
}

func writeMinioAPIError(w http.ResponseWriter, err error) {
	var s3err minio.ErrorResponse
	if errors.As(err, &s3err) {
		switch s3err.Code {
		case "NoSuchKey", "NotFound":
			writeAPIError(w, http.StatusNotFound, "not_found", "object not found")
			return
		}
	}
	writeAPIError(w, http.StatusBadGateway, "storage_error", "could not read object")
}

func (h *UploadHandlers) pipeMinioObject(
	w http.ResponseWriter,
	r *http.Request,
	bucket, objectKey string,
	contentTypeFallback string,
	attachment bool,
	filenameForCD string,
) {
	if h.Store == nil || h.Store.Client == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "object storage not configured")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Minute)
	defer cancel()

	core := minio.Core{Client: h.Store.Client}
	opts := minio.GetObjectOptions{}
	if rng := r.Header.Get("Range"); rng != "" {
		opts.Set("Range", rng)
	}

	reader, _, hdr, err := core.GetObject(ctx, bucket, objectKey, opts)
	if err != nil {
		writeMinioAPIError(w, err)
		return
	}
	defer reader.Close()

	code := http.StatusOK
	if hdr.Get("Content-Range") != "" {
		code = http.StatusPartialContent
	}
	for _, k := range []string{"Content-Type", "Content-Length", "Content-Range", "ETag", "Last-Modified"} {
		if v := hdr.Get(k); v != "" {
			w.Header().Set(k, v)
		}
	}
	w.Header().Set("Accept-Ranges", "bytes")
	if w.Header().Get("Content-Type") == "" && contentTypeFallback != "" {
		w.Header().Set("Content-Type", contentTypeFallback)
	}
	w.Header().Set("Content-Disposition", contentDispositionInlineOrAttachment(attachment, filenameForCD))

	w.WriteHeader(code)
	_, _ = io.Copy(w, reader)
}

func (h *UploadHandlers) streamUploadOriginal(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
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
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
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

	if h.Store == nil || h.Store.Client == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "object storage not configured")
		return
	}

	attachment := r.URL.Query().Get("download") == "1"

	if r.Method == http.MethodHead {
		info, err := h.Store.Client.StatObject(ctx, u.Bucket, u.ObjectKey, minio.StatObjectOptions{})
		if err != nil {
			writeMinioAPIError(w, err)
			return
		}
		ct := u.ContentType
		if ct == "" {
			ct = info.ContentType
		}
		if ct == "" {
			ct = "application/octet-stream"
		}
		w.Header().Set("Content-Type", ct)
		w.Header().Set("Content-Length", fmt.Sprintf("%d", info.Size))
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("Content-Disposition", contentDispositionInlineOrAttachment(attachment, u.OriginalFilename))
		w.WriteHeader(http.StatusOK)
		return
	}

	ct := u.ContentType
	if ct == "" {
		ct = "application/octet-stream"
	}
	h.pipeMinioObject(w, r, u.Bucket, u.ObjectKey, ct, attachment, u.OriginalFilename)
}

func (h *UploadHandlers) streamUploadRedacted(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
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
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
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
			writeAPIError(w, http.StatusNotFound, "not_found", "processing job not found")
			return
		}
		writeAPIError(w, http.StatusInternalServerError, "internal_error", "could not load processing job")
		return
	}
	if job.UserID != uid {
		writeAPIError(w, http.StatusNotFound, "not_found", "upload not found")
		return
	}
	if job.RedactedAudioBucket == nil || job.RedactedAudioObjectKey == nil {
		writeAPIError(w, http.StatusNotFound, "not_found", "redacted audio not available")
		return
	}
	if job.Status != "done" {
		writeAPIError(w, http.StatusNotFound, "not_ready", "redacted audio not ready")
		return
	}

	bucket := *job.RedactedAudioBucket
	key := *job.RedactedAudioObjectKey
	attachment := r.URL.Query().Get("download") == "1"
	dlName := "redacted_" + u.OriginalFilename

	if r.Method == http.MethodHead {
		if h.Store == nil || h.Store.Client == nil {
			writeAPIError(w, http.StatusServiceUnavailable, "service_unavailable", "object storage not configured")
			return
		}
		info, err := h.Store.Client.StatObject(ctx, bucket, key, minio.StatObjectOptions{})
		if err != nil {
			writeMinioAPIError(w, err)
			return
		}
		ct := info.ContentType
		if ct == "" {
			ct = u.ContentType
		}
		if ct == "" {
			ct = "application/octet-stream"
		}
		w.Header().Set("Content-Type", ct)
		w.Header().Set("Content-Length", fmt.Sprintf("%d", info.Size))
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("Content-Disposition", contentDispositionInlineOrAttachment(attachment, dlName))
		w.WriteHeader(http.StatusOK)
		return
	}

	ct := u.ContentType
	if ct == "" {
		ct = "application/octet-stream"
	}
	h.pipeMinioObject(w, r, bucket, key, ct, attachment, dlName)
}
