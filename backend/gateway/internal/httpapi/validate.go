package httpapi

import (
	"regexp"
	"strings"
	"unicode/utf8"
)

var usernameRe = regexp.MustCompile(`^[a-zA-Z0-9_]{3,32}$`)

func validateUsername(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return "username is required"
	}
	if !usernameRe.MatchString(s) {
		return "username must be 3–32 characters: letters, digits, underscore"
	}
	return ""
}

func validatePassword(s string) string {
	if s == "" {
		return "password is required"
	}
	n := utf8.RuneCountInString(s)
	if n < 8 {
		return "password must be at least 8 characters"
	}
	if n > 128 {
		return "password must be at most 128 characters"
	}
	return ""
}
