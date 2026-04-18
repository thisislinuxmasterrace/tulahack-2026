package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
)

func NewRefreshToken() (raw string, hash []byte, err error) {
	var b [32]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", nil, err
	}
	raw = base64.RawURLEncoding.EncodeToString(b[:])
	h := sha256.Sum256([]byte(raw))
	return raw, h[:], nil
}

func HashRefresh(raw string) []byte {
	h := sha256.Sum256([]byte(raw))
	return h[:]
}
