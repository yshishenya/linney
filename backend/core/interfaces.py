"""
@doc Core Interfaces for Clean Architecture

Определяет интерфейсы для dependency injection и инверсии зависимостей.
Позволяет слоям более высокого уровня зависеть от абстракций, а не от конкретных реализаций.

Examples:
    python>
    from core.interfaces import AuthInterface
    # Используется для dependency injection в middleware
"""

from typing import Protocol, Optional, Dict, Any


class AuthInterface(Protocol):
    """
    @doc Интерфейс для сервиса авторизации
    
    Определяет контракт для работы с JWT токенами и авторизацией пользователей.
    Позволяет middleware зависеть от абстракции, а не от конкретной реализации.
    
    Examples:
        python>
        class MyAuthService:
            def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
                # Реализация проверки токена
                return {"user_id": "123", "username": "admin"}
    """
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify the validity of a JWT token.
        
        Args:
            token: JWT token to verify.
        
        Returns:
            User data if the token is valid, None if not.
        """
        ...