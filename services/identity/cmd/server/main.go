package main

import (
	"log/slog"
	"net/http"
	"os"

	"stockapp/identity/internal/router"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8081"
	}

	addr := ":" + port
	logger.Info("identity service starting", "addr", addr)

	if err := http.ListenAndServe(addr, router.New(logger)); err != nil {
		logger.Error("server stopped", "err", err)
		os.Exit(1)
	}
}
