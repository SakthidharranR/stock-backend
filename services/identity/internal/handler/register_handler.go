package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"stockapp/identity/internal/model"
	"stockapp/identity/internal/service"
)

type RegisterHandler struct {
	svc    *service.RegisterService
	logger *slog.Logger
}

func NewRegisterHandler(svc *service.RegisterService, logger *slog.Logger) *RegisterHandler {
	return &RegisterHandler{svc: svc, logger: logger}
}

func (h *RegisterHandler) Register(w http.ResponseWriter, r *http.Request) {
	var req model.RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	result, err := h.svc.Register(req)
	if err != nil {
		msg := err.Error()
		if msg == "email is required" || msg == "cognito_sub is required" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
			return
		}
		h.logger.Error("register failed", "err", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal server error"})
		return
	}

	writeJSON(w, http.StatusCreated, result)
}

func Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}
