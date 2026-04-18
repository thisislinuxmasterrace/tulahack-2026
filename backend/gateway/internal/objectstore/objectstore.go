package objectstore

import (
	"context"
	"os"
	"strings"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

// Store — S3-совместимый клиент и имя бакета (MinIO).
type Store struct {
	Client *minio.Client
	Bucket string
}

// FromEnv — nil, если S3_ENDPOINT пуст; иначе клиент и при необходимости создание бакета.
func FromEnv(ctx context.Context) (*Store, error) {
	endpoint := strings.TrimSpace(os.Getenv("S3_ENDPOINT"))
	if endpoint == "" {
		return nil, nil
	}
	access := strings.TrimSpace(os.Getenv("S3_ACCESS_KEY"))
	secret := strings.TrimSpace(os.Getenv("S3_SECRET_KEY"))
	if access == "" || secret == "" {
		return nil, errMissingCreds()
	}
	bucket := strings.TrimSpace(os.Getenv("S3_BUCKET"))
	if bucket == "" {
		bucket = "app"
	}
	useSSL := strings.EqualFold(strings.TrimSpace(os.Getenv("S3_USE_SSL")), "true") ||
		strings.TrimSpace(os.Getenv("S3_USE_SSL")) == "1"

	cli, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(access, secret, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, err
	}
	exists, err := cli.BucketExists(ctx, bucket)
	if err != nil {
		return nil, err
	}
	if !exists {
		if err := cli.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			return nil, err
		}
	}
	return &Store{Client: cli, Bucket: bucket}, nil
}

func errMissingCreds() error {
	return errConfig("S3_ACCESS_KEY and S3_SECRET_KEY are required when S3_ENDPOINT is set")
}

type configError string

func (e configError) Error() string { return string(e) }

func errConfig(msg string) error {
	return configError(msg)
}

// PingStatus — для health: "disabled", "ok" или "error: …".
func PingStatus(ctx context.Context, s *Store) string {
	if s == nil || s.Client == nil {
		return "disabled"
	}
	ok, err := s.Client.BucketExists(ctx, s.Bucket)
	if err != nil {
		return "error: " + err.Error()
	}
	if !ok {
		return "error: bucket missing"
	}
	return "ok"
}
