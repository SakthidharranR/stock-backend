import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from app.auth import AuthUser, get_current_user, set_user_store
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_cors_origins, get_database_url, redact_db_url
from app.cognito_users import lookup_password_options
from app.models import (
    ErrorResponse,
    PasswordOptionsRequest,
    PasswordOptionsResponse,
    RegisterRequest,
    RegisterResponse,
    UserMeResponse,
)
from app.service import RegisterService
from app.store import UserStore, open_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_store: UserStore | None = None


def get_store() -> UserStore:
    if _store is None:
        raise RuntimeError("User store is not initialized")
    return _store


def get_register_service(store: UserStore = Depends(get_store)) -> RegisterService:
    return RegisterService(store)


def create_app(store: UserStore | None = None) -> FastAPI:
    global _store

    app = FastAPI(title="Stock Identity Service", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Dev-Email"],
    )

    if store is not None:
        _store = store
    else:
        database_url = get_database_url()
        logger.info("using database url=%s", redact_db_url(database_url))
        _store = open_store(database_url)

    set_user_store(_store)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/users/me", response_model=UserMeResponse)
    def users_me(user: AuthUser = Depends(get_current_user)) -> UserMeResponse:
        return UserMeResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
        )

    @app.post(
        "/auth/password-options",
        response_model=PasswordOptionsResponse,
        responses={400: {"model": ErrorResponse}},
    )
    def password_options(body: PasswordOptionsRequest) -> PasswordOptionsResponse:
        email = body.email.strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="email is required")
        result = lookup_password_options(email)
        return PasswordOptionsResponse(**result)

    @app.post(
        "/register",
        response_model=RegisterResponse,
        status_code=201,
        responses={
            400: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def register(
        body: RegisterRequest,
        service: RegisterService = Depends(get_register_service),
    ):
        try:
            return service.register(body)
        except ValueError as err:
            return JSONResponse(status_code=400, content={"error": str(err)})
        except Exception:
            logger.exception("register failed")
            return JSONResponse(
                status_code=500,
                content={"error": "internal server error"},
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid request body"},
        )

    return app


def create_application() -> FastAPI:
    """Uvicorn factory entrypoint."""
    return create_app()
