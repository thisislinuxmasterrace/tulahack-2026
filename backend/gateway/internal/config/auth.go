package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Auth struct {
	JWTSecret       []byte
	AccessTTL       time.Duration
	RefreshTTL      time.Duration
}

func AuthFromEnv() (Auth, error) {
	secret := strings.TrimSpace(os.Getenv("JWT_SECRET"))
	if secret == "" {
		return Auth{}, errMissing("JWT_SECRET")
	}
	if len(secret) < 16 {
		return Auth{}, errInvalid("JWT_SECRET", "at least 16 characters")
	}
	accessSec := 900
	if v := strings.TrimSpace(os.Getenv("JWT_ACCESS_TTL_SEC")); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 60 || n > 86400 {
			return Auth{}, errInvalid("JWT_ACCESS_TTL_SEC", "integer 60..86400")
		}
		accessSec = n
	}
	refreshSec := 7 * 24 * 3600
	if v := strings.TrimSpace(os.Getenv("JWT_REFRESH_TTL_SEC")); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 3600 || n > 365*24*3600 {
			return Auth{}, errInvalid("JWT_REFRESH_TTL_SEC", "integer 3600..31536000")
		}
		refreshSec = n
	}
	return Auth{
		JWTSecret:  []byte(secret),
		AccessTTL:  time.Duration(accessSec) * time.Second,
		RefreshTTL: time.Duration(refreshSec) * time.Second,
	}, nil
}

type configError string

func (e configError) Error() string { return string(e) }

func errMissing(name string) error {
	return configError("missing required environment variable: " + name)
}

func errInvalid(name, hint string) error {
	return configError("invalid " + name + ": expected " + hint)
}
