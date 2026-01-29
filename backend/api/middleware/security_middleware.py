"""
@doc Security Headers Middleware

Middleware для добавления security headers в API layer.

Examples:
    python>
    app.add_middleware(SecurityHeadersMiddleware)
    # Добавляет безопасные HTTP headers ко всем ответам
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)

from ...core.config import config


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    @doc Middleware для добавления security headers

    Добавляет важные заголовки безопасности ко всем ответам.
    Размещен в API layer так как обрабатывает HTTP responses.

    Examples:
        python>
        app.add_middleware(SecurityHeadersMiddleware)
        # Автоматически добавляет X-Content-Type-Options, X-Frame-Options, etc.
    """

    async def dispatch(self, request: Request, call_next):
        """
        @doc Добавление security headers к ответу

        Examples:
            python>
            # Автоматически добавляет security headers:
            # X-Content-Type-Options: nosniff
            # X-Frame-Options: DENY
            # X-XSS-Protection: 1; mode=block
            # Content-Security-Policy: ...
        """

        response = await call_next(request)

        # Добавляем security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Строгий Content Security Policy для производства
        # В разработке более мягкий CSP для работы с документацией
        if config.ENVIRONMENT == "production":
            # Avoid 'unsafe-eval' in production.
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "worker-src blob:;"
            )
        else:
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "worker-src blob:;"
            )
        response.headers["Content-Security-Policy"] = csp

        return response
