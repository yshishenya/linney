"""
@doc
Конфигурация frontend приложения Linney.

Управляет настройками через environment variables для
интеграции с backend API и настройки UI.

Examples:
  python> config = FrontendConfig()
  python> print(config.BACKEND_URL)  # http://localhost:8022
"""

import os
from pathlib import Path

# Загружаем переменные из .env файла
try:
    from dotenv import load_dotenv

    # Ищем .env файл в корне проекта (на уровень выше от frontend/)
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Frontend loaded environment from: {env_path}")
    else:
        print(f"⚠️  .env file not found at: {env_path}")

except ImportError:
    print("📦 python-dotenv not available, using system environment variables only")


class FrontendConfig:
    """
    @doc
    Конфигурация frontend приложения.

    Централизованное управление всеми настройками NiceGUI приложения
    через environment variables.

    Examples:
      python> config = FrontendConfig()
      python> print(f"Backend: {config.BACKEND_URL}")
      python> print(f"Debug: {config.DEBUG}")
    """

    # =============================================================================
    # NiceGUI Server Settings
    # =============================================================================

    HOST: str = os.getenv("FRONTEND_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("FRONTEND_PORT", "8033"))
    TITLE: str = os.getenv("FRONTEND_TITLE", "Linney")

    # =============================================================================
    # Environment & Debug
    # =============================================================================

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = ENVIRONMENT == "development"

    # =============================================================================
    # Backend Integration
    # =============================================================================

    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "localhost")
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8022"))

    @property
    def BACKEND_URL(self) -> str:
        """URL для подключения к FastAPI backend"""
        # В Docker контейнерах всегда используем HTTP для внутреннего взаимодействия
        protocol = "http"
        return f"{protocol}://{self.BACKEND_HOST}:{self.BACKEND_PORT}"

    # =============================================================================
    # API Settings
    # =============================================================================

    API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "30"))  # seconds
    API_RETRY_ATTEMPTS: int = int(os.getenv("API_RETRY_ATTEMPTS", "3"))

    # =============================================================================
    # UI Settings
    # =============================================================================

    THEME: str = os.getenv("FRONTEND_THEME", "auto")  # auto, light, dark
    LANGUAGE: str = os.getenv("FRONTEND_LANGUAGE", "ru")  # ru, en

    # Material Design colors
    PRIMARY_COLOR: str = os.getenv("PRIMARY_COLOR", "blue")
    SECONDARY_COLOR: str = os.getenv("SECONDARY_COLOR", "grey")

    # =============================================================================
    # Session & Auth
    # =============================================================================

    SESSION_TIMEOUT_MINUTES: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
    AUTO_REFRESH_TOKEN: bool = os.getenv("AUTO_REFRESH_TOKEN", "true").lower() == "true"
    STORAGE_SECRET: str = os.getenv(
        "STORAGE_SECRET", "linney-frontend-storage-secret-key"
    )

    # =============================================================================
    # Features Flags
    # =============================================================================

    ENABLE_REGISTRATION: bool = (
        os.getenv("ENABLE_REGISTRATION", "false").lower() == "true"
    )
    ENABLE_PASSWORD_RESET: bool = (
        os.getenv("ENABLE_PASSWORD_RESET", "false").lower() == "true"
    )
    ENABLE_DARK_MODE_TOGGLE: bool = (
        os.getenv("ENABLE_DARK_MODE_TOGGLE", "true").lower() == "true"
    )

    # =============================================================================
    # Static Files
    # =============================================================================

    STATIC_DIR: str = os.getenv("FRONTEND_STATIC_DIR", "frontend/static")
    FAVICON_PATH: str = os.getenv("FAVICON_PATH", "🏢")  # Emoji или путь к файлу

    # =============================================================================
    # Logging
    # =============================================================================

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    ENABLE_REQUEST_LOGGING: bool = (
        os.getenv("ENABLE_REQUEST_LOGGING", "false").lower() == "true"
    )

    # =============================================================================
    # Development Settings
    # =============================================================================

    HOT_RELOAD: bool = DEBUG
    AUTO_OPEN_BROWSER: bool = DEBUG
    SHOW_NICEGUI_LOGS: bool = DEBUG

    # =============================================================================
    # Validation & Utilities
    # =============================================================================

    def validate(self) -> bool:
        """
        @doc
        Валидация конфигурации frontend.

        Проверяет критически важные настройки и выводит предупреждения
        для production окружения.

        Examples:
          python> config = FrontendConfig()
          python> if not config.validate(): print("Configuration issues found")
        """

        issues = []

        # Проверяем доступность backend
        if not self.BACKEND_HOST or not self.BACKEND_PORT:
            issues.append("❌ Backend host/port не настроены!")

        # Проверяем production настройки
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                issues.append("⚠️  DEBUG не должен быть включен в production!")

            if self.HOST == "0.0.0.0" and self.PORT == 8033:
                issues.append("⚠️  Используются настройки по умолчанию в production!")

        # Выводим предупреждения
        if issues:
            print("🚨 ПРОБЛЕМЫ КОНФИГУРАЦИИ FRONTEND:")
            for issue in issues:
                print(f"  {issue}")
            return False

        print("✅ Конфигурация frontend валидна")
        return True

    def print_summary(self):
        """
        @doc
        Печать сводки конфигурации frontend.

        Выводит основные настройки приложения без секретной информации.

        Examples:
          python> config.print_summary()
          python> # Выводится таблица настроек
        """

        print(
            f"""
🎨 Linney Frontend Configuration Summary:
   Environment: {self.ENVIRONMENT}
   Debug: {self.DEBUG}
   Server: {self.HOST}:{self.PORT}
   Backend: {self.BACKEND_URL}
   Theme: {self.THEME}
   Language: {self.LANGUAGE}
   API Timeout: {self.API_TIMEOUT}s
   Session Timeout: {self.SESSION_TIMEOUT_MINUTES}m
   Hot Reload: {self.HOT_RELOAD}
   Auto Open Browser: {self.AUTO_OPEN_BROWSER}
        """
        )

    def get_nicegui_config(self) -> dict:
        """
        @doc
        Получение конфигурации для ui.run().

        Возвращает словарь параметров для запуска NiceGUI сервера.

        Examples:
          python> config = FrontendConfig()
          python> ui.run(**config.get_nicegui_config())
        """

        return {
            "host": self.HOST,
            "port": self.PORT,
            "title": self.TITLE,
            "favicon": self.FAVICON_PATH,
            "dark": self.THEME if self.THEME != "auto" else None,
            "reload": self.HOT_RELOAD,
            "show": self.AUTO_OPEN_BROWSER,
        }


# =============================================================================
# ДОПОЛНИТЕЛЬНЫЕ УТИЛИТЫ
# =============================================================================


def get_version() -> str:
    """
    @doc
    Получение версии приложения из environment или файла.

    Ищет версию в переменной окружения VERSION или файле версии.

    Examples:
      python> version = get_version()
      python> print(f"Version: {version}")
    """

    # Из environment variable
    version = os.getenv("VERSION")
    if version:
        return version

    # Из файла версии
    try:
        version_file = Path(__file__).parent.parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    except (OSError, UnicodeDecodeError) as e:
        # Fallback to default version
        print(f"⚠️  Failed to read VERSION file: {e}")

    # По умолчанию
    return "1.0.0-dev"


def is_production() -> bool:
    """Проверка production окружения"""
    return FrontendConfig().ENVIRONMENT == "production"


def is_development() -> bool:
    """Проверка development окружения"""
    return FrontendConfig().ENVIRONMENT == "development"


def get_static_path() -> Path:
    """Получение пути к статическим файлам"""
    return Path(__file__).parent.parent / "static"


# =============================================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР КОНФИГУРАЦИИ
# =============================================================================

# Создаем глобальный экземпляр для использования во всем приложении
config = FrontendConfig()


if __name__ == "__main__":
    # Тестирование конфигурации
    print("🧪 Testing Linney Frontend Configuration...")

    config.print_summary()
    config.validate()

    print(f"\n📋 NiceGUI config: {config.get_nicegui_config()}")
    print(f"📦 Version: {get_version()}")
    print(f"🏭 Production: {is_production()}")
    print(f"🛠️  Development: {is_development()}")

    print("\n✅ Frontend configuration test completed!")
