package config

import (
	"os"
	"strings"
)

// S3PublicBaseURL — базовый URL для ссылок в ответах API (без завершающего /).
// Нужен при отдаче метаданных загрузок (например http://127.0.0.1:9000).
func S3PublicBaseURL() string {
	return strings.TrimRight(strings.TrimSpace(os.Getenv("S3_PUBLIC_BASE_URL")), "/")
}
