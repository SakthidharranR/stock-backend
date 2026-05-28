# Placeholder — replace with your Go build once cmd/server exists.
# Example final stage:
#   FROM golang:1.22-alpine AS build
#   WORKDIR /app
#   COPY go.mod go.sum ./
#   RUN go mod download
#   COPY . .
#   RUN CGO_ENABLED=0 go build -o /identity ./cmd/server
#   FROM alpine:3.19
#   COPY --from=build /identity /identity
#   EXPOSE 8081
#   CMD ["/identity"]

FROM alpine:3.19
RUN echo "Build identity Go service before enabling docker compose profile full"
CMD ["sleep", "infinity"]
