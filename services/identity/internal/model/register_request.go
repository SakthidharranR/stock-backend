package model

type RegisterRequest struct {
	CognitoSub  string `json:"cognito_sub,omitempty"`
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	Password    string `json:"password,omitempty"`
}
