package auth

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
)

const accessClaimType = "access"

type jwtClaims struct {
	Type string `json:"typ"`
	jwt.RegisteredClaims
}

func IssueAccess(secret []byte, userID uuid.UUID, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := jwtClaims{
		Type: accessClaimType,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID.String(),
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	t := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return t.SignedString(secret)
}

func ParseAccess(secret []byte, tokenString string) (uuid.UUID, error) {
	tok, err := jwt.ParseWithClaims(tokenString, &jwtClaims{}, func(t *jwt.Token) (any, error) {
		if t.Method != jwt.SigningMethodHS256 {
			return nil, fmt.Errorf("unexpected signing method")
		}
		return secret, nil
	})
	if err != nil {
		return uuid.Nil, err
	}
	claims, ok := tok.Claims.(*jwtClaims)
	if !ok || !tok.Valid {
		return uuid.Nil, errors.New("invalid token")
	}
	if claims.Type != accessClaimType {
		return uuid.Nil, errors.New("invalid token type")
	}
	if claims.Subject == "" {
		return uuid.Nil, errors.New("missing subject")
	}
	id, err := uuid.Parse(claims.Subject)
	if err != nil {
		return uuid.Nil, err
	}
	return id, nil
}
