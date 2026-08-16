from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    display_name: str = ""
    cognito_sub: str = ""
    password: str | None = None


class UserMeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None = None


class RegisterResponse(BaseModel):
    email: str
    display_name: str
    cognito_sub: str
    message: str


class ErrorResponse(BaseModel):
    error: str


class PasswordOptionsRequest(BaseModel):
    email: str


class PasswordOptionsResponse(BaseModel):
    email: str
    found: bool
    can_use_password: bool
    providers: list[str] = []
    message: str | None = None
