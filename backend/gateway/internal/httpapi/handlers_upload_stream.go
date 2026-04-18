package httpapi

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"path"
	"regexp"
	"strconv"
	"strings"
	"time"

	"tulahack/gateway/internal/store"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/minio/minio-go/v7"
)

// Safari/WebKit строго проверяют 206: Content-Length должен совпадать с диапазоном в Content-Range,
// total в Content-Range — с реальным размером объекта. Прокси иногда портят Content-Length (gzip).
var contentRangeHeaderRe = regexp.MustCompile(`(?i)^bytes\s+(\d+)-(\d+)/(\d+|\*)$`)

func rewritePartialContentHeaders(h http.Header, objectSize int64) {
	cr := strings.TrimSpace(h.Get("Content-Range"))
	if cr == "" {
		return
	}
	m := contentRangeHeaderRe.FindStringSubmatch(cr)
	if m == nil {
		return
	}
	start, err1 := strconv.ParseInt(m[1], 10, 64)
	end, err2 := strconv.ParseInt(m[2], 10, 64)
	if err1 != nil || err2 != nil || end < start || start < 0 {
		return
	}
	cl := end - start + 1
	if cl <= 0 {
		return
	}
	totalPart := m[3]
	if totalPart == "*" {
		if objectSize >= 0 {
			h.Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, objectSize))
		}
		h.Set("Content-Length", strconv.FormatInt(cl, 10))
		return
	}
	total, err := strconv.ParseInt(totalPart, 10, 64)
	if err != nil {
		return
	}
	if objectSize >= 0 && total != objectSize {
		total = objectSize
	}
	h.Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, total))
	h.Set("Content-Length", strconv.FormatInt(cl, 10))
}

func (h *UploadHandlers) RegisterStreamRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/uploads/{id}/original", BearerUserIDHeaderOrQuery(h.JWT, h.streamUploadOriginal))
	mux.HandleFunc("GET /api/v1/uploads/{id}/redacted-audio", BearerUserIDHeaderOrQuery(h.JWT, h.streamUploadRedacted))
}

// normalizeStreamContentType — Safari хуже Chrome относится к MP3 с Content-Type: application/octet-stream.
func normalizeStreamContentType(ct, filename string) string {
	ct = strings.TrimSpace(ct)
	ext := strings.ToLower(path.Ext(strings.TrimSpace(filename)))
	if ext != ".mp3" {
		return ct
	}
	low := strings.ToLower(ct)
	if ct == "" || low == "application/octet-stream" || low == "binary/octet-stream" {
		return "audio/mpeg"
	}
	return ct
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
	rng := r.Header.Get("Range")
	if rng != "" {
		opts.Set("Range", rng)
	}

	var objectSize int64 = -1
	if rng != "" {
		if info, err := h.Store.Client.StatObject(ctx, bucket, objectKey, minio.StatObjectOptions{}); err == nil {
			objectSize = info.Size
		}
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
	// Не проксируем Content-/Transfer-Encoding: иначе прокси может отдать gzip и сломать длину тела для Safari.
	w.Header().Del("Content-Encoding")
	w.Header().Del("Transfer-Encoding")

	for _, k := range []string{"Content-Type", "Content-Length", "Content-Range", "ETag", "Last-Modified"} {
		if v := hdr.Get(k); v != "" {
			w.Header().Set(k, v)
		}
	}
	if hdr.Get("Content-Range") != "" {
		rewritePartialContentHeaders(w.Header(), objectSize)
	}
	w.Header().Set("Accept-Ranges", "bytes")
	if w.Header().Get("Content-Type") == "" && contentTypeFallback != "" {
		w.Header().Set("Content-Type", contentTypeFallback)
	}
	ctOut := normalizeStreamContentType(w.Header().Get("Content-Type"), filenameForCD)
	if ctOut != "" {
		w.Header().Set("Content-Type", ctOut)
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
		w.Header().Set("Content-Type", normalizeStreamContentType(ct, u.OriginalFilename))
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
	ct = normalizeStreamContentType(ct, u.OriginalFilename)
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
		w.Header().Set("Content-Type", normalizeStreamContentType(ct, dlName))
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
	ct = normalizeStreamContentType(ct, dlName)
	h.pipeMinioObject(w, r, bucket, key, ct, attachment, dlName)
}
