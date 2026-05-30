package store

import (
	"database/sql"
	"log/slog"
	"context"
)

type UserStore struct{ 
	db *sql.DB
	logger *slog.Logger
}

func NewUserStore(db *sql.DB, logger *slog.Logger) *UserStore {
	return &UserStore{db: db, logger: logger}
}

func (s *UserStore) CreateUser(ctx context.Context, cognitoSub string, email string, displayName string) error {
	_, err:= s.db.ExecContext(ctx, "INSERT INTO users (cognito_sub, email, display_name) VALUES ($1, $2, $3)", cognitoSub, email, displayName)
	return err
}