"""
@doc JWT Authentication Middleware

Middleware для автоматической проверки JWT токенов в API layer.
Размещен здесь, так как отвечает за HTTP authentication.

Examples:
    python>
    middleware = JWTAuthMiddleware(app, auth_service)
    # Автоматически проверяет JWT токены для защищенных endpoints
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime
import logging

from ...core.interfaces import AuthInterface

logger = logging.getLogger(__name__)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    @doc Middleware для автоматической проверки JWT токенов

    Применяется ко всем защищенным endpoints автоматически.
    Размещен в API layer так как обрабатывает HTTP requests.

    Examples:
        python>
        middleware = JWTAuthMiddleware(app, auth_service)
        # Все API endpoints будут проверять JWT автоматически
    """

    # Endpoints, которые не требуют авторизации
    EXEMPT_PATHS = {
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/auth/login",
        "/api/auth/validate",
        "/static",
    }

    def __init__(self, app, auth_service: AuthInterface):
        super().__init__(app)
        self.auth_service = auth_service

    async def dispatch(self, request: Request, call_next):

        # Проверяем, нужна ли авторизация для этого пути
        """Handle request with authorization check.
        
        This function processes incoming requests by checking if authorization is
        required for the requested path.  It allows unauthenticated access to exempt
        paths and static resources. If authorization is needed, it  extracts the Bearer
        token from the Authorization header, verifies it using the auth_service, and
        adds  user information to the request state. If any checks fail, appropriate
        JSON responses are returned.
        
        Args:
            request (Request): The incoming request object.
            call_next: A callable to process the request further.
        """
        path = request.url.path

        # Пропускаем неавторизованные пути
        if (
            path in self.EXEMPT_PATHS
            or path.startswith("/static/")
            or path.startswith("/docs")
            or path.startswith("/redoc")
        ):
            return await call_next(request)

        # Извлекаем токен из заголовка Authorization
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "error": "Требуется авторизация",
                    "detail": "Отсутствует токен авторизации",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        # Извлекаем токен
        token = auth_header.split(" ")[1]

        # Проверяем токен через services layer (допустимо в API layer)
        if self.auth_service is None:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "error": "Сервис авторизации не инициализирован",
                    "detail": "Internal server error",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        user_data = self.auth_service.verify_token(token)

        if not user_data:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "error": "Недействительный токен",
                    "detail": "Токен авторизации недействителен или истек",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        # Добавляем информацию о пользователе в request state
        request.state.user = user_data

        # Продолжаем обработку запроса
        return await call_next(request)