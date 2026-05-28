package service

import(
	"log/slog"
	"stockapp/identity/internal/model"
)

type RegisterService struct {
	logger *slog.Logger
}

func NewRegisterService(Logger *slog.Logger) *RegisterService{
	return &RegisterService{logger: logger}
}

type RegisterResult struct {
	Email string `json: "email"`
	DisplayName string `json: "display_name"`
	Message string `json: "message"`
}

func (s *RegisterService) Register(req model.RegisterRequest)(RegisterResult, error){
	email:= strings.TrimSpace(strings.ToLower(req.Email))
	displayname:= strings.TrimSpace(req.DisplayName)

	//Not checking if email is valid because they should have already been validated by Cognito

	s.logger.Info("registering user", "email", email, "displayname", displayname)

	return RegisterResult{
		Email: email,
		DisplayName: displayname,
		Message: "User registered successfully!",
	}
}