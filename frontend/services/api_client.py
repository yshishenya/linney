"""
@doc
HTTP клиент для взаимодействия с FastAPI backend.

Обеспечивает авторизацию через JWT токены, автоматическое обновление токенов,
и обработку ошибок API. Используется во всех frontend компонентах.

Examples:
  python> client = APIClient("http://localhost:8022")
  python> result = await client.login("admin", "admin123")
  python> if result["success"]: print("Logged in!")
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import httpx
from nicegui import ui

from ..utils.config import config as frontend_config

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Исключение для ошибок API"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class APIClient:
    """
    @doc
    HTTP клиент для взаимодействия с FastAPI backend.

    Поддерживает JWT аутентификацию, автоматическое обновление токенов,
    и централизованную обработку ошибок API.

    Examples:
      python> client = APIClient("http://localhost:8022")
      python> await client.login("admin", "password")
      python> profile = await client.get_profile("123")
    """

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._remember_me: bool = False

        # Race condition protection
        self._refresh_lock: Optional[asyncio.Lock] = None
        self._token_loading_lock: Optional[asyncio.Lock] = None

        # HTTP клиент с настройками
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        # Загружаем токены из NiceGUI storage
        self._load_tokens_from_storage()
        logger.debug("APIClient initialized")

    def _ensure_locks(self):
        """Инициализация asyncio locks для предотвращения race conditions"""
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        if self._token_loading_lock is None:
            self._token_loading_lock = asyncio.Lock()

    def _load_tokens_from_storage(self):
        """Загрузка токенов из NiceGUI storage и localStorage (синхронная версия)"""
        logger.debug("_load_tokens_from_storage: Starting token loading process")

        try:
            from nicegui import app

            # Загружаем из NiceGUI storage
            if hasattr(app, "storage") and hasattr(app.storage, "user"):
                token_data = app.storage.user.get("token_data")
                if token_data:
                    self._access_token = token_data.get("access_token")
                    expires_timestamp = token_data.get("expires_timestamp")
                    self._remember_me = token_data.get("remember_me", False)

                    # Восстанавливаем expires_at из timestamp
                    if expires_timestamp:
                        self._token_expires_at = datetime.fromtimestamp(
                            expires_timestamp
                        )

                        # Проверяем не истек ли токен
                        if datetime.now() >= self._token_expires_at:
                            logger.info("Token expired, clearing from storage")
                            self._clear_expired_token()
                            return

                    if self._access_token:
                        logger.info("Loaded access token from NiceGUI storage")
                        return

            # Если remember_me был установлен, пробуем загрузить из localStorage (dev only)
            try:
                from nicegui import ui

                if frontend_config.ENVIRONMENT != "production" and hasattr(ui, "run_javascript"):
                    # Используем более длинный timeout и обработку ошибок
                    try:
                        token_data_str = ui.run_javascript(
                            'localStorage.getItem("hr_token_data")',
                            timeout=3.0,  # Увеличили timeout
                        )

                        if (
                            token_data_str
                            and token_data_str.strip()
                            and token_data_str != "null"
                        ):
                            token_data = json.loads(token_data_str)

                            # Валидация данных
                            if not isinstance(token_data, dict) or not token_data.get(
                                "access_token"
                            ):
                                logger.warning("Invalid token data in localStorage")
                                return

                            self._access_token = token_data.get("access_token")
                            expires_timestamp = token_data.get("expires_timestamp")
                            self._remember_me = token_data.get("remember_me", False)

                            # Восстанавливаем expires_at из timestamp
                            if expires_timestamp:
                                try:
                                    self._token_expires_at = datetime.fromtimestamp(
                                        float(expires_timestamp)
                                    )

                                    # Проверяем не истек ли токен
                                    if datetime.now() >= self._token_expires_at:
                                        logger.info(
                                            "Token expired, clearing from localStorage"
                                        )
                                        self._clear_expired_token()
                                        return
                                except (ValueError, TypeError) as e:
                                    logger.warning(
                                        f"Invalid timestamp in token data: {e}"
                                    )
                                    return

                            # Только если все валидно, синхронизируем с NiceGUI storage
                            if hasattr(app, "storage") and hasattr(app.storage, "user"):
                                app.storage.user["token_data"] = token_data
                            logger.info("Loaded access token from localStorage")
                            return

                    except asyncio.TimeoutError:
                        logger.warning("localStorage access timed out")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in localStorage: {e}")
                        # Очищаем невалидные данные
                        try:
                            ui.run_javascript(
                                'localStorage.removeItem("hr_token_data")', timeout=1.0
                            )
                        except Exception as e:
                            logger.debug("Failed to clear invalid localStorage token", exc_info=e)

            except Exception as browser_e:
                logger.debug(f"Could not load from browser storage: {browser_e}")

        except Exception as e:
            logger.debug(f"Could not load tokens from storage: {e}")

        # Fallback: загружаем из environment variables (только для разработки)
        if not self._access_token and frontend_config.ENVIRONMENT != "production":
            import os

            test_token = os.getenv("TEST_JWT_TOKEN")
            if test_token:
                self._access_token = test_token
                logger.info("✅ Loaded TEST_JWT_TOKEN from environment variables")
            else:
                logger.debug("TEST_JWT_TOKEN not found in environment variables")

        logger.debug(
            f"_load_tokens_from_storage: Final token state={'present' if self._access_token else 'None/empty'}"
        )

    def _save_tokens_to_storage(self):
        """Сохранение токенов с учетом remember_me"""
        try:
            from nicegui import app
            if not self._access_token:
                return

            # Подготавливаем данные токена
            token_data = {
                "access_token": self._access_token,
                "remember_me": self._remember_me,
                "expires_timestamp": (
                    self._token_expires_at.timestamp()
                    if self._token_expires_at
                    else None
                ),
            }

            # Всегда сохраняем в NiceGUI storage (session storage)
            if hasattr(app, "storage") and hasattr(app.storage, "user"):
                app.storage.user["token_data"] = token_data
                app.storage.user["authenticated"] = True

            # Если remember_me=True, также сохраняем в localStorage (dev only)
            if self._remember_me and frontend_config.ENVIRONMENT != "production":
                try:
                    from nicegui import ui

                    if hasattr(ui, "run_javascript"):
                        token_data_str = json.dumps(token_data)
                        ui.run_javascript(
                            f'localStorage.setItem("hr_token_data", {json.dumps(token_data_str)})'
                        )
                        logger.debug("Saved token to localStorage (remember_me=True)")
                except Exception as browser_e:
                    logger.debug(f"Could not save to localStorage: {browser_e}")
            else:
                # Если remember_me=False, убираем из localStorage
                try:
                    from nicegui import ui

                    if hasattr(ui, "run_javascript"):
                        ui.run_javascript('localStorage.removeItem("hr_token_data")')
                        logger.debug(
                            "Removed token from localStorage (remember_me=False)"
                        )
                except Exception as browser_e:
                    logger.debug(f"Could not remove from localStorage: {browser_e}")

            logger.info(f"Saved tokens to storage (remember_me={self._remember_me})")
        except Exception as e:
            logger.debug(f"Could not save tokens to storage: {e}")

    def _get_auth_headers(self) -> Dict[str, str]:
        """Получение заголовков авторизации"""
        if self._access_token:
            # DEBUG: Log token info (first 10 chars for security)
            token_preview = (
                self._access_token[:10] + "..."
                if len(self._access_token) > 10
                else self._access_token
            )
            logger.debug(
                f"_get_auth_headers: Creating Authorization header with token {token_preview}"
            )
            return {"Authorization": f"Bearer {self._access_token}"}

        logger.warning(
            "_get_auth_headers: No token available - returning empty headers"
        )
        return {}

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        require_auth: bool = True,
    ) -> Dict[str, Any]:
        """
        @doc
        Выполнение HTTP запроса к API.

        Автоматически добавляет авторизационные заголовки,
        обрабатывает ошибки и логирует запросы.

        Examples:
          python> response = await client._make_request("POST", "/auth/login", {"username": "admin"})
          python> data = response["data"]
        """

        url = f"{self.base_url}{endpoint}"
        headers = {}

        # DEBUG: Log initial token state
        logger.debug(
            f"_make_request: require_auth={require_auth}, self._access_token={'present' if self._access_token else 'None/empty'}"
        )

        if require_auth:
            # Проверяем и обновляем токен при необходимости
            token_valid = await self._ensure_valid_token()
            logger.debug(f"_make_request: _ensure_valid_token returned {token_valid}")

            if not token_valid:
                logger.error(
                    f"_make_request: No valid token for {method} {endpoint}, raising APIError"
                )
                raise APIError("Не удалось получить валидный токен авторизации", 401)

            auth_headers = self._get_auth_headers()
            logger.debug(f"_make_request: auth_headers = {auth_headers}")
            headers.update(auth_headers)

        try:
            logger.debug(
                f"Making {method} request to {url} with headers: {list(headers.keys())}"
            )

            response = await self.client.request(
                method=method, url=url, json=data, params=params, headers=headers
            )

            # Логируем ответ
            logger.debug(f"Response {response.status_code} from {url}")

            # Проверяем статус
            if response.status_code >= 400:
                error_data = {}
                try:
                    error_data = response.json()
                except (ValueError, json.JSONDecodeError) as e:
                    logger.debug("Failed to decode error JSON", exc_info=e)

                error_message = error_data.get("detail", f"HTTP {response.status_code}")
                raise APIError(
                    message=error_message,
                    status_code=response.status_code,
                    details=error_data,
                )

            return response.json()

        except httpx.TimeoutException:
            logger.error(f"Timeout for request to {url}")
            raise APIError("Превышено время ожидания ответа от сервера")

        except httpx.NetworkError as e:
            logger.error(f"Network error for {url}: {e}")
            raise APIError(f"Ошибка сети: {str(e)}")

        except APIError:
            raise

        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}")
            raise APIError(f"Неожиданная ошибка: {str(e)}")

    async def _ensure_valid_token(self) -> bool:
        """Проверка и автоматическое обновление токена при необходимости"""
        self._ensure_locks()  # Обеспечиваем что locks инициализированы

        logger.debug(
            f"_ensure_valid_token: self._access_token={'present' if self._access_token else 'None/empty'}"
        )

        if not self._access_token:
            logger.warning("_ensure_valid_token: No access token available")
            return False

        # Проверяем срок действия токена
        if self._token_expires_at:
            now = datetime.now()

            # Если токен истек или скоро истечет
            if now >= self._token_expires_at:
                logger.info("Access token expired, attempting refresh")
                # Используем блокировку чтобы предотвратить множественные refresh
                async with self._refresh_lock:
                    # Проверяем еще раз после получения блокировки
                    if (
                        self._token_expires_at
                        and datetime.now() < self._token_expires_at
                    ):
                        logger.debug("Token was refreshed by another request")
                        return True
                    return await self._refresh_token_internal()

            # Если токен истекает в ближайшие 5 минут - обновляем превентивно
            elif (self._token_expires_at - now).total_seconds() < 300:
                logger.info("Access token expires soon, refreshing preemptively")
                async with self._refresh_lock:
                    # Проверяем еще раз после получения блокировки
                    if (
                        self._token_expires_at
                        and (self._token_expires_at - datetime.now()).total_seconds()
                        >= 300
                    ):
                        logger.debug("Token was refreshed by another request")
                        return True
                    return await self._refresh_token_internal()

        logger.debug("_ensure_valid_token: Token is valid")
        return True

    async def _refresh_token_internal(self) -> bool:
        """Внутренний метод для обновления токена через /api/auth/refresh"""
        try:
            # Используем текущий токен для запроса обновления
            headers = {"Authorization": f"Bearer {self._access_token}"}

            response = await self.client.request(
                method="POST", url=f"{self.base_url}/api/auth/refresh", headers=headers
            )

            if response.status_code == 200:
                data = response.json()

                if data.get("access_token"):
                    self._access_token = data["access_token"]

                    # Обновляем время истечения
                    expires_in = data.get("expires_in", 24 * 3600)
                    self._token_expires_at = datetime.now() + timedelta(
                        seconds=expires_in
                    )

                    # Сохраняем обновленный токен
                    self._save_tokens_to_storage()

                    logger.info("Successfully refreshed access token")
                    return True

            logger.error(f"Token refresh failed: {response.status_code}")
            self._clear_expired_token()
            return False

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            # Не очищаем токен при сетевых ошибках - он может еще быть валидным
            if (
                "network" in str(e).lower()
                or "timeout" in str(e).lower()
                or "connection" in str(e).lower()
            ):
                logger.warning(
                    f"Network error during token refresh, keeping existing token: {e}"
                )
                return False  # Оставляем токен как есть
            else:
                # Очищаем токен только при ошибках аутентификации
                self._clear_expired_token()
                return False

    def _clear_expired_token(self):
        """Очищаем истекший токен из всех хранилищ"""
        # Используем общую логику очистки, но не трогаем remember_me
        remember_me_backup = self._remember_me
        self._clear_all_tokens()
        self._remember_me = remember_me_backup

    async def login(
        self, username: str, password: str, remember_me: bool = False
    ) -> Dict[str, Any]:
        """
        @doc
        Авторизация пользователя в системе.

        Отправляет учетные данные на backend и сохраняет полученный JWT токен.
        Возвращает информацию о пользователе и статус авторизации.

        Examples:
          python> result = await client.login("admin", "admin123")
          python> if result["success"]: print("Successfully logged in")
        """

        login_data = {
            "username": username,
            "password": password,
            "remember_me": remember_me,
        }

        try:
            response = await self._make_request(
                "POST", "/api/auth/login", data=login_data, require_auth=False
            )

            # Сохраняем токены с учетом remember_me
            if response.get("access_token"):
                self._access_token = response["access_token"]
                self._remember_me = remember_me

                # Рассчитываем время истечения токена
                expires_in = response.get("expires_in", 24 * 3600)  # seconds
                self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                # Сохраняем с учетом remember_me
                self._save_tokens_to_storage()

                logger.info(
                    f"Successfully logged in user: {username} (remember_me={remember_me})"
                )

            return response

        except APIError as e:
            logger.error(f"Login failed for user {username}: {e.message}")
            raise

    async def logout(self) -> Dict[str, Any]:
        """
        @doc
        Выход пользователя из системы.

        Инвалидирует токен на backend и очищает локальные данные авторизации.

        Examples:
          python> result = await client.logout()
          python> print(result["message"])
        """

        try:
            response = await self._make_request("POST", "/api/auth/logout")

            # Очищаем все данные токенов
            self._clear_all_tokens()

            logger.info("Successfully logged out")
            return response

        except APIError as e:
            # Даже если backend logout не удался, очищаем локальные данные
            self._clear_all_tokens()
            logger.debug(f"Logout failed on backend (clearing local data): {e.message}")
            return {"success": True, "message": "Локальный выход выполнен"}

    def _clear_all_tokens(self):
        """Полная очистка всех токенов и связанных данных"""
        self._access_token = None
        self._token_expires_at = None
        self._remember_me = False

        try:
            from nicegui import app, ui

            # Очищаем NiceGUI storage
            if hasattr(app, "storage") and hasattr(app.storage, "user"):
                app.storage.user.pop("token_data", None)
                app.storage.user.pop("authenticated", None)

            # Очищаем localStorage
            if hasattr(ui, "run_javascript"):
                ui.run_javascript('localStorage.removeItem("hr_token_data")')
                logger.debug("Cleared tokens from all storages")

        except Exception as e:
            logger.debug(f"Could not clear token storages: {e}")

    async def validate_token(self, token: Optional[str] = None) -> bool:
        """
        @doc
        Проверка валидности токена.

        Отправляет запрос на backend для проверки действительности токена.

        Examples:
          python> is_valid = await client.validate_token()
          python> if not is_valid: print("Need to login again")
        """

        if token:
            old_token = self._access_token
            self._access_token = token

        try:
            await self._make_request("GET", "/api/auth/validate")
            return True

        except APIError:
            return False

        finally:
            if token and "old_token" in locals():
                self._access_token = old_token

    def is_authenticated(self) -> bool:
        """Проверка состояния авторизации"""
        return bool(
            self._access_token
            and (not self._token_expires_at or datetime.now() < self._token_expires_at)
        )

    def get_token(self) -> Optional[str]:
        """Получение текущего токена"""
        return self._access_token

    async def _get_auth_headers_async(self) -> Dict[str, str]:
        """
        @doc
        Получение заголовков авторизации для внешних запросов (асинхронная версия).

        Используется для ручных HTTP запросов (например, скачивания файлов).

        Examples:
          python> headers = await client._get_auth_headers_async()
          python> response = httpx.get(url, headers=headers)
        """
        # Убедимся, что токен валиден перед получением заголовков
        if await self._ensure_valid_token():
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        @doc
        Получение заголовков авторизации для внешних запросов.

        Используется для ручных HTTP запросов (например, скачивания файлов).

        Examples:
          python> headers = client._get_auth_headers()
          python> response = httpx.get(url, headers=headers)
        """
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    async def get_departments(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        @doc
        Получение списка департаментов для navigation.

        Examples:
          python> deps = await client.get_departments()
          python> print(f"Found {len(deps['data']['departments'])} departments")
        """
        params = {"force_refresh": force_refresh} if force_refresh else None
        return await self._make_request(
            "GET", "/api/catalog/departments", params=params
        )

    async def get_positions(
        self, department: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        @doc
        Получение должностей для конкретного департамента.

        Examples:
          python> positions = await client.get_positions("IT Department")
          python> print(f"Found {len(positions['data']['positions'])} positions")
        """
        params = {"force_refresh": force_refresh} if force_refresh else None
        return await self._make_request(
            "GET", f"/api/catalog/positions/{department}", params=params
        )

    async def get_organization_search_items(self) -> Dict[str, Any]:
        """
        @doc
        Получение элементов для поиска из организационной структуры.

        Возвращает все департаменты и позиции для автокомплита поиска.

        Examples:
          python> items = await client.get_organization_search_items()
          python> print(f"Total items: {len(items['data']['items'])}")
        """
        return await self._make_request("GET", "/api/organization/search-items")

    async def get_profiles_list(
        self,
        page: int = 1,
        limit: int = 20,
        department: Optional[str] = None,
        position: Optional[str] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        @doc
        Получение списка профилей с фильтрацией.

        Examples:
          python> profiles = await client.get_profiles_list(department="IT")
          python> print(f"Found {profiles['pagination']['total']} profiles")
        """
        params = {"page": page, "limit": limit}
        if department:
            params["department"] = department
        if position:
            params["position"] = position
        if search:
            params["search"] = search
        if status:
            params["status"] = status

        return await self._make_request("GET", "/api/profiles/", params=params)

    async def get_profile_by_id(self, profile_id: str) -> Dict[str, Any]:
        """
        @doc
        Получение конкретного профиля по ID.

        Examples:
          python> profile = await client.get_profile_by_id("uuid-here")
          python> print(f"Profile: {profile['position']}")
        """
        return await self._make_request("GET", f"/api/profiles/{profile_id}")

    async def download_profile_json(self, profile_id: str) -> bytes:
        logger.debug("Attempting to download JSON for profile %s", profile_id)
        """
        @doc
        Скачивание профиля в JSON формате.

        Args:
            profile_id: ID профиля для скачивания

        Returns:
            bytes: Содержимое JSON файла

        Examples:
          python> data = await client.download_profile_json("profile123")
          python> # Получены байты JSON файла
        """
        url = f"{self.base_url}/api/profiles/{profile_id}/download/json"
        headers = await self._get_auth_headers_async()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Ошибка скачивания: {e.response.status_code}",
                status_code=e.response.status_code,
            )
        except Exception as e:
            raise APIError(f"Ошибка сети при скачивании: {e}")

    async def download_profile_markdown(self, profile_id: str) -> bytes:
        """
        @doc
        Скачивание профиля в Markdown формате.

        Args:
            profile_id: ID профиля для скачивания

        Returns:
            bytes: Содержимое Markdown файла

        Examples:
          python> data = await client.download_profile_markdown("profile123")
          python> # Получены байты Markdown файла
        """
        url = f"{self.base_url}/api/profiles/{profile_id}/download/md"
        headers = await self._get_auth_headers_async()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Ошибка скачивания: {e.response.status_code}",
                status_code=e.response.status_code,
            )
        except Exception as e:
            raise APIError(f"Ошибка сети при скачивании: {e}")

    async def start_profile_generation(
        self,
        department: str,
        position: str,
        employee_name: Optional[str] = None,
        temperature: float = 0.1,
        save_result: bool = True,
    ) -> Dict[str, Any]:
        """
        @doc
        Запуск генерации профиля должности.

        Examples:
          python> task = await client.start_profile_generation("IT", "Developer")
          python> print(f"Task ID: {task['task_id']}")
        """
        data = {
            "department": department,
            "position": position,
            "temperature": temperature,
            "save_result": save_result,
        }
        if employee_name:
            data["employee_name"] = employee_name

        return await self._make_request("POST", "/api/generation/start", data=data)

    async def get_generation_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        @doc
        Получение статуса задачи генерации.

        Examples:
          python> status = await client.get_generation_task_status(task_id)
          python> print(f"Progress: {status['task']['progress']}%")
        """
        return await self._make_request("GET", f"/api/generation/{task_id}/status")

    async def get_generation_task_result(self, task_id: str) -> Dict[str, Any]:
        """
        @doc
        Получение результата генерации профиля.

        Examples:
          python> result = await client.get_generation_task_result(task_id)
          python> print(f"Profile generated: {result['success']}")
        """
        return await self._make_request("GET", f"/api/generation/{task_id}/result")

    async def cancel_generation_task(self, task_id: str) -> Dict[str, Any]:
        """
        @doc
        Отмена задачи генерации.

        Examples:
          python> result = await client.cancel_generation_task(task_id)
          python> print(f"Cancelled: {result['message']}")
        """
        return await self._make_request("DELETE", f"/api/generation/{task_id}")

    async def get_dashboard_stats(self) -> Optional[Dict[str, Any]]:
        """
        @doc
        Получение единой статистики для dashboard.

        Оптимизированный метод для получения всей статистики одним запросом.
        Возвращает данные о департаментах, должностях, профилях и активных задачах.

        Examples:
          python> stats = await client.get_dashboard_stats()
          python> print(f"Positions: {stats['positions_count']}")
        """
        try:
            response = await self._make_request("GET", "/api/dashboard/stats/minimal")
            if response and response.get("success"):
                return response["data"]
            else:
                logger.warning("Failed to get dashboard stats from API")
                # Fallback данные для graceful degradation
                return {
                    "positions_count": 1553,
                    "profiles_count": 0,
                    "completion_percentage": 0.0,
                    "active_tasks_count": 0,
                    "last_updated": datetime.now().isoformat(),
                }
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            # Fallback данные при ошибке
            return {
                "positions_count": 1553,
                "profiles_count": 0,
                "completion_percentage": 0.0,
                "active_tasks_count": 0,
                "last_updated": datetime.now().isoformat(),
            }

    def _reload_tokens_from_storage(self):
        """
        @doc
        Публичный метод для перезагрузки токенов из storage.

        Используется после логина или когда нужно обновить токены
        в уже существующем экземпляре APIClient.

        Examples:
          python> api_client._reload_tokens_from_storage()
          python> # Токены будут загружены из NiceGUI storage или localStorage
        """
        logger.info("reload_tokens_from_storage: Manual token reload requested")
        old_token_state = "present" if self._access_token else "None/empty"

        self._load_tokens_from_storage()

        new_token_state = "present" if self._access_token else "None/empty"
        logger.info(
            f"reload_tokens_from_storage: Token state changed from {old_token_state} to {new_token_state}"
        )

    async def close(self):
        """Закрытие HTTP клиента"""
        await self.client.aclose()

    def __del__(self):
        """Cleanup при удалении объекта"""
        try:
            asyncio.create_task(self.close())
        except RuntimeError as e:
            # No running event loop (common at interpreter shutdown)
            logger.debug("APIClient cleanup skipped: no running loop", exc_info=e)
        except Exception as e:
            logger.debug("APIClient cleanup failed", exc_info=e)


# ============================================================================
# UTILITY FUNCTIONS


def handle_api_error(error: APIError, context: str = "API request") -> None:
    """
    @doc
    Обработка ошибок API с пользовательскими уведомлениями.

    Отображает соответствующие уведомления в UI в зависимости от типа ошибки.

    Examples:
      python> try:
      python>   await client.login("wrong", "pass")
      python> except APIError as e:
      python>   handle_api_error(e, "login")
    """

    logger.error(f"{context} failed: {error.message}")

    # Определяем тип уведомления и сообщение
    if error.status_code == 401:
        ui.notify("Неверные учетные данные", type="negative", icon="lock")
    elif error.status_code == 403:
        ui.notify("Недостаточно прав доступа", type="negative", icon="block")
    elif error.status_code == 404:
        ui.notify("Ресурс не найден", type="negative", icon="search_off")
    elif error.status_code == 500:
        ui.notify("Ошибка сервера. Попробуйте позже", type="negative", icon="error")
    elif error.status_code and error.status_code >= 400:
        ui.notify(f"Ошибка: {error.message}", type="negative", icon="warning")
    else:
        ui.notify(
            f"Ошибка соединения: {error.message}", type="negative", icon="wifi_off"
        )

    async def download_profile_json(self, profile_id: str) -> bytes:
        logger.debug("Attempting to download JSON for profile %s", profile_id)
        """
        @doc
        Скачивание профиля в JSON формате.

        Args:
            profile_id: ID профиля для скачивания

        Returns:
            bytes: Содержимое JSON файла

        Examples:
          python> data = await client.download_profile_json("profile123")
          python> # Получены байты JSON файла
        """
        url = f"{self.base_url}/api/profiles/{profile_id}/download/json"
        headers = await self._get_auth_headers_async()  # Обновлено: сделано асинхронным
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Ошибка скачивания: {e.response.status_code}",
                status_code=e.response.status_code,
            )
        except Exception as e:
            raise APIError(f"Ошибка сети при скачивании: {e}")

    async def download_profile_markdown(self, profile_id: str) -> bytes:
        """
        @doc
        Скачивание профиля в Markdown формате.

        Args:
            profile_id: ID профиля для скачивания

        Returns:
            bytes: Содержимое Markdown файла

        Examples:
          python> data = await client.download_profile_markdown("profile123")
          python> # Получены байты Markdown файла
        """
        url = f"{self.base_url}/api/profiles/{profile_id}/download/md"
        headers = await self._get_auth_headers_async()  # Обновлено: сделано асинхронным
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"Ошибка скачивания: {e.response.status_code}",
                status_code=e.response.status_code,
            )
        except Exception as e:
            raise APIError(f"Ошибка сети при скачивании: {e}")


if __name__ == "__main__":
    # Простой тест API клиента
    async def test_client():
        client = APIClient("http://localhost:8022")

        try:
            # Тест неверного логина
            try:
                await client.login("wrong", "password")
            except APIError as e:
                print(f"❌ Expected login error: {e.message}")

        except APIError as e:
            print(f"❌ API Error: {e.message}")
        finally:
            await client.close()

    asyncio.run(test_client())
