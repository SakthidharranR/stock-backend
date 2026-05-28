package router

import (
	"log/slog"
	"net/http"

	"stockapp/identity/internal/handler"
	"stockapp/identity/internal/service"
)

func New(logger *slog.Logger) http.Handler {
	registerSvc := service.NewRegisterService(logger)
	registerHandler := handler.NewRegisterHandler(registerSvc, logger)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handler.Health)
	mux.HandleFunc("POST /register", registerHandler.Register)

	return corsMiddleware(mux)
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "http://localhost:5173")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}
