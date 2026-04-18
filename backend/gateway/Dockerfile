FROM golang:1.22-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN go build -trimpath -ldflags="-s -w" -o /gateway ./cmd/gateway

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /gateway /gateway
# не root (в alpine есть пользователь nobody)
USER nobody
ENV GATEWAY_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/gateway"]
