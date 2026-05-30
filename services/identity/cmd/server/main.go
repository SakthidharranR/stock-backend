package main

import (
	"database/sql"
	"log/slog"
	"net/http"
	"os"
	"regexp"

	"github.com/joho/godotenv"
	_ "github.com/jackc/pgx/v5/stdlib"

	"stockapp/identity/internal/router"
	"stockapp/identity/internal/store"
)

func loadEnv() {
	// Overload so services/identity/.env wins over a stale shell DATABASE_URL.
	for _, path := range []string{".env", "services/identity/.env"} {
		if err := godotenv.Overload(path); err == nil {
			return
		}
	}
}

func redactDBURL(url string) string {
	return regexp.MustCompile(`://([^:@]+):([^@]*)@`).ReplaceAllString(url, "://$1:***@")
}

func main() {
	loadEnv()

	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8081"
	}

	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		logger.Error("DATABASE_URL is not set")
		os.Exit(1)
	}
	logger.Info("using database", "url", redactDBURL(dbURL))

	db, err := sql.Open("pgx", dbURL)
	if err != nil {
		logger.Error("failed to open database", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	if err := db.Ping(); err != nil {
		logger.Error("failed to ping database", "err", err)
		os.Exit(1)
	}

	userStore := store.NewUserStore(db, logger)

	addr := ":" + port
	logger.Info("identity service starting", "addr", addr)

	if err := http.ListenAndServe(addr, router.New(logger, userStore)); err != nil {
		logger.Error("server stopped", "err", err)
		os.Exit(1)
	}
}
