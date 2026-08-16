import logging

from psycopg.errors import UniqueViolation

from app.models import RegisterRequest, RegisterResponse
from app.store import UserStore

logger = logging.getLogger(__name__)


class RegisterService:
    def __init__(self, store: UserStore) -> None:
        self._store = store

    def register(self, req: RegisterRequest) -> RegisterResponse:
        email = req.email.strip().lower()
        display_name = req.display_name.strip()
        cognito_sub = req.cognito_sub.strip()

        if not email:
            raise ValueError("email is required")
        if not cognito_sub:
            raise ValueError("cognito_sub is required")

        try:
            self._store.create_user(cognito_sub, email, display_name)
        except UniqueViolation:
            logger.info(
                "user already registered email=%s cognito_sub=%s",
                email,
                cognito_sub,
            )
            return RegisterResponse(
                email=email,
                display_name=display_name,
                cognito_sub=cognito_sub,
                message="User already registered",
            )
        except Exception:
            logger.exception(
                "failed to create user cognito_sub=%s email=%s",
                cognito_sub,
                email,
            )
            raise

        logger.info(
            "registered user email=%s display_name=%s cognito_sub=%s",
            email,
            display_name,
            cognito_sub,
        )
        return RegisterResponse(
            email=email,
            display_name=display_name,
            cognito_sub=cognito_sub,
            message="User registered successfully!",
        )