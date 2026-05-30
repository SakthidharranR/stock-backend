package service

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"github.com/jackc/pgx/v5/pgconn"
	"stockapp/identity/internal/model"
	"stockapp/identity/internal/store"
)

type RegisterService struct {
	logger *slog.Logger
	store *store.UserStore
}

func NewRegisterService(logger *slog.Logger, store *store.UserStore) *RegisterService {
	return &RegisterService{logger: logger, store: store}
}

type RegisterResult struct {
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	CognitoSub  string `json:"cognito_sub"`
	Message     string `json:"message"`
}

func (s *RegisterService) Register(req model.RegisterRequest) (RegisterResult, error) {
	email := strings.TrimSpace(strings.ToLower(req.Email))
	displayName := strings.TrimSpace(req.DisplayName)
	cognitoSub := strings.TrimSpace(req.CognitoSub)

	if email == "" {
		return RegisterResult{}, errors.New("email is required")
	}
	if cognitoSub == "" {
		return RegisterResult{}, errors.New("cognito_sub is required")
	}

	err := s.store.CreateUser(context.Background(), cognitoSub, email, displayName)
	if err != nil {
		if isUniqueViolation(err) {
			s.logger.Info("user already registered", "email", email, "cognito_sub", cognitoSub)
			return RegisterResult{
				Email:       email,
				DisplayName: displayName,
				CognitoSub:  cognitoSub,
				Message:     "User already registered",
			}, nil
		}
		s.logger.Error("failed to create user", "err", err, "cognito_sub", cognitoSub, "email", email)
		return RegisterResult{}, err
	}

	s.logger.Info("registered user", "email", email, "display_name", displayName, "cognito_sub", cognitoSub)

	return RegisterResult{
		Email:       email,
		DisplayName: displayName,
		CognitoSub:  cognitoSub,
		Message:     "User registered successfully!",
	}, nil
}

func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}