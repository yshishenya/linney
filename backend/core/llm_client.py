"""
LLM клиент для интеграции с Gemini 2.5 Flash через Langfuse OpenAI pattern.

Поддерживает:
- Интеграция с Langfuse для промптов и мониторинга
- OpenRouter API через langfuse.openai
- Structured output с JSON schema
- Автоматический трейсинг и логирование
"""

import json
import logging
import asyncio
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import anyio
from langfuse import Langfuse
from langfuse.openai import AsyncOpenAI

from .config import config
from .prompt_manager import PromptManager

logger = logging.getLogger(__name__)

# Константы
PROMPT_CACHE_TTL_SECONDS = 300  # 5 минут кеш для промптов
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY_SECONDS = 1.0


class LLMClient:
    """
    Клиент для работы с Gemini 2.5 Flash через Langfuse OpenAI integration
    """

    def __init__(
        self,
        openrouter_api_key: Optional[str] = None,
        langfuse_public_key: Optional[str] = None,
        langfuse_secret_key: Optional[str] = None,
        langfuse_host: Optional[str] = None,
    ):
        """
        Инициализация LLM клиента с Langfuse интеграцией.
        Использует config для получения настроек из .env

        Args:
            openrouter_api_key: API ключ OpenRouter (или из config)
            langfuse_public_key: Langfuse public key (или из config)
            langfuse_secret_key: Langfuse secret key (или из config)
            langfuse_host: Langfuse host URL (или из config)
        """
        # Получаем настройки из config если не переданы
        self.openrouter_api_key = openrouter_api_key or config.OPENROUTER_API_KEY
        self.langfuse_public_key = langfuse_public_key or config.LANGFUSE_PUBLIC_KEY
        self.langfuse_secret_key = langfuse_secret_key or config.LANGFUSE_SECRET_KEY
        self.langfuse_host = langfuse_host or config.LANGFUSE_HOST

        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY не найден в .env или параметрах")

        # Инициализируем Langfuse
        if self.langfuse_public_key and self.langfuse_secret_key:
            self.langfuse = Langfuse(
                public_key=self.langfuse_public_key,
                secret_key=self.langfuse_secret_key,
                host=self.langfuse_host,
            )
            logger.info("✅ Langfuse initialized from config")
        else:
            logger.warning(
                "⚠️ Langfuse credentials not found in config - tracing disabled"
            )
            self.langfuse = None

        # 🔥 НОВАЯ ФИЧА: Инициализируем PromptManager для fallback и синхронизации
        self.prompt_manager = PromptManager(
            langfuse_client=self.langfuse,
            templates_dir=config.TEMPLATES_DIR,  # Используем путь из конфигурации
            cache_ttl=PROMPT_CACHE_TTL_SECONDS,
        )
        logger.info("✅ PromptManager initialized with Langfuse sync")

        # Инициализируем AsyncOpenAI клиент через Langfuse для параллельной работы
        self.client = AsyncOpenAI(
            api_key=self.openrouter_api_key,
            base_url=config.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://a101-hr-profiles.local",
                "X-Title": "A101 HR Profile Generator",
            },
        )
        logger.info(f"✅ Async LLM client initialized with model: {config.OPENROUTER_MODEL}")

    async def _create_generation_with_prompt(
        self,
        prompt: Optional[Any],
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Any],
        trace_metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Внутренняя асинхронная функция для создания generation с правильной связкой промпта.

        Используется в качестве декорированной функции для Langfuse tracing.
        Выполняет асинхронный вызов OpenAI API через AsyncOpenAI клиент.

        Args:
            prompt: Langfuse prompt object (может быть None при fallback)
            messages: Список сообщений для API в формате ChatML
            model: Название модели (например, "google/gemini-2.5-flash")
            temperature: Температура генерации (0.0-2.0)
            max_tokens: Максимальное количество токенов в ответе
            response_format: Формат ответа (JSON schema или None)
            trace_metadata: Метаданные для трейсинга (опционально)

        Returns:
            ChatCompletion response объект от OpenAI SDK

        Raises:
            httpx.HTTPStatusError: При ошибках HTTP (4xx, 5xx)
            httpx.TimeoutException: При таймауте запроса

        Examples:
            >>> result = await self._create_generation_with_prompt(
            ...     prompt, messages, "google/gemini-2.5-flash", 0.1, 4000, None, {}
            ... )
        """
        # Обогащенные metadata для полного трекинга (убираем только prompt content)
        enriched_metadata = {
            # Параметры модели
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format_type": (
                type(response_format).__name__ if response_format else None
            ),
            # Информация о промпте (без содержимого)
            "prompt_length": len(str(messages)),
            "messages_count": len(messages),
            # НЕ добавляем prompt_first_100_chars - занимает место
            # Trace metadata (исключает json_schema, company_map, org_structure)
            **(trace_metadata or {}),
        }

        # Правильная связка промпта согласно документации 2025 года (асинхронный вызов)
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            langfuse_prompt=prompt,  # 🔗 КЛЮЧЕВАЯ связка с промптом!
            metadata=enriched_metadata,
        )

        # Дополнительное обогащение metadata после получения ответа
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            post_metadata = {
                **enriched_metadata,
                # Основная информация о response
                "response_id": getattr(response, "id", None),
                "created_timestamp": getattr(response, "created", None),
                "actual_model": getattr(response, "model", model),
                "system_fingerprint": getattr(response, "system_fingerprint", None),
                # Провайдер информация из OpenRouter
                "provider": (
                    response.model_extra.get("provider", "openrouter")
                    if hasattr(response, "model_extra") and response.model_extra
                    else "openrouter"
                ),
                # Детальная информация о токенах
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                # Дополнительные детали токенов (из model_extra если есть)
                "prompt_tokens_cached": 0,
                "completion_reasoning_tokens": 0,
                "completion_image_tokens": 0,
                # Информация о завершении
                "finish_reason": (
                    response.choices[0].finish_reason if response.choices else None
                ),
                "choice_index": response.choices[0].index if response.choices else None,
                "response_length": (
                    len(response.choices[0].message.content)
                    if response.choices and response.choices[0].message
                    else 0
                ),
                # Попробуем извлечь cost информацию (может быть в headers или других местах)
                "cost_usd": getattr(usage, "cost", None),
                "cost_estimated": None,  # Можем добавить расчёт на основе токенов позже
                # Статус и провайдер
                "success": True,
                "api_provider": "openrouter",
                "langfuse_sdk_version": "3.3.4",
                "openai_sdk_version": (
                    response.__class__.__module__
                    if hasattr(response.__class__, "__module__")
                    else "unknown"
                ),
            }

            # Извлекаем детальную token информацию если доступна
            try:
                if hasattr(usage, "model_extra") and usage.model_extra:
                    if "prompt_tokens_details" in usage.model_extra:
                        post_metadata["prompt_tokens_cached"] = usage.model_extra[
                            "prompt_tokens_details"
                        ].get("cached_tokens", 0)
                    if "completion_tokens_details" in usage.model_extra:
                        completion_details = usage.model_extra[
                            "completion_tokens_details"
                        ]
                        post_metadata["completion_reasoning_tokens"] = (
                            completion_details.get("reasoning_tokens", 0)
                        )
                        post_metadata["completion_image_tokens"] = (
                            completion_details.get("image_tokens", 0)
                        )
            except Exception as e:
                logger.warning(f"⚠️ Failed to extract detailed token info: {e}")

            # Обновляем generation с обогащенными метаданными (если возможно)
            try:
                if self.langfuse:
                    self.langfuse.update_current_generation(
                        metadata=post_metadata,
                        usage_details={
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "total_tokens": usage.total_tokens,
                        },
                    )
            except Exception as e:
                # Логируем но не прерываем выполнение
                logger.warning(f"⚠️ Failed to update generation metadata: {e}")

        return response

    def _get_prompt_and_config(
        self, prompt_name: str
    ) -> tuple[Optional[Any], Dict[str, Any]]:
        """
        Получение промпта из Langfuse и конфигурации с fallback.

        Args:
            prompt_name: Имя промпта в Langfuse

        Returns:
            Tuple из (prompt_obj, config)
        """
        prompt_obj = None
        if self.langfuse:
            try:
                prompt_obj = self.langfuse.get_prompt(prompt_name, label="production")
                logger.info(f"✅ Retrieved prompt from Langfuse directly: {prompt_name}")
            except (httpx.HTTPError, ConnectionError, TimeoutError) as langfuse_error:
                logger.warning(
                    "Failed to get prompt from Langfuse",
                    extra={
                        "error": str(langfuse_error),
                        "prompt_name": prompt_name,
                        "error_type": type(langfuse_error).__name__
                    }
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error getting prompt from Langfuse",
                    extra={"prompt_name": prompt_name}
                )

        # Извлекаем конфигурацию с fallback через PromptManager
        config = self.prompt_manager.get_prompt_config(
            "profile_generation", environment="production"
        )

        return prompt_obj, config

    async def _get_prompt_and_config_async(
        self, prompt_name: str
    ) -> tuple[Optional[Any], Dict[str, Any]]:
        """Async wrapper to avoid blocking event loop on Langfuse calls."""

        def _get_sync() -> tuple[Optional[Any], Dict[str, Any]]:
            return self._get_prompt_and_config(prompt_name)

        return await anyio.to_thread.run_sync(_get_sync)

    def _is_retryable_exception(self, exc: Exception) -> bool:
        """Best-effort retry classification for transient API errors."""
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
            return True

        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code if exc.response else None
            return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

        # OpenAI SDK exceptions (avoid importing; rely on names)
        retryable_names = {
            "RateLimitError",
            "APITimeoutError",
            "APIConnectionError",
            "InternalServerError",
            "ServiceUnavailableError",
        }
        if type(exc).__name__ in retryable_names:
            return True

        return False

    async def _sleep_before_retry(self, attempt: int) -> None:
        delay = min(
            LLM_RETRY_BASE_DELAY_SECONDS * (2**attempt),
            20.0,
        )
        # jitter
        delay = delay * (0.8 + random.random() * 0.4)
        await asyncio.sleep(delay)

    def _compile_prompt_to_messages(
        self, prompt_obj: Optional[Any], variables: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Компиляция промпта в формат messages.

        Args:
            prompt_obj: Объект промпта из Langfuse или None
            variables: Переменные для подстановки

        Returns:
            Список messages для API запроса
        """
        if prompt_obj:
            # Если промпт получен из Langfuse - используем compile()
            compiled_prompt = prompt_obj.compile(**variables)
            logger.info(f"Compiled prompt using Langfuse compile(), type: {type(compiled_prompt)}")
        else:
            # Fallback: используем PromptManager для получения промпта и подстановки
            logger.warning("⚠️ Using local fallback prompt from PromptManager")
            compiled_prompt = self.prompt_manager.get_prompt(
                "profile_generation", variables=variables
            )
            logger.info(f"Compiled prompt using PromptManager fallback, length: {len(compiled_prompt)}")

        # Преобразуем в формат messages если нужно
        if isinstance(compiled_prompt, str):
            messages = [{"role": "user", "content": compiled_prompt}]
            logger.info(f"Converted string prompt to messages format, length: {len(compiled_prompt)}")
        elif isinstance(compiled_prompt, list):
            messages = compiled_prompt
            logger.info(f"Using existing messages format, count: {len(messages)}")
        else:
            raise ValueError(f"Unexpected prompt format: {type(compiled_prompt)}")

        return messages

    def _build_trace_metadata(
        self,
        prompt_name: str,
        prompt_obj: Optional[Any],
        variables: Dict[str, Any],
        user_id: Optional[str],
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Построение метаданных для трейсинга.

        Args:
            prompt_name: Имя промпта
            prompt_obj: Объект промпта
            variables: Переменные генерации
            user_id: ID пользователя
            session_id: ID сессии

        Returns:
            Словарь метаданных
        """
        return {
            "prompt_name": prompt_name,
            "prompt_version": getattr(prompt_obj, "version", "local_fallback"),
            "department": variables.get("department"),
            "position": variables.get("position"),
            "employee_name": variables.get("employee_name"),
            "user_id": user_id,
            "session_id": session_id,
            "environment": "production",
            "source": "hr_profile_generator",
            "prompt_source": "langfuse" if prompt_obj else "local_fallback",
        }

    def _build_success_response(
        self,
        profile_json: Dict[str, Any],
        generated_text: str,
        model: str,
        generation_time: float,
        usage: Any,
        prompt_obj: Optional[Any],
        prompt_name: str,
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Построение успешного ответа генерации.

        Args:
            profile_json: Распарсенный JSON профиля
            generated_text: Сырой текст ответа
            model: Имя модели
            generation_time: Время генерации
            usage: Объект с данными использования токенов
            prompt_obj: Объект промпта
            prompt_name: Имя промпта
            variables: Переменные генерации

        Returns:
            Словарь с результатом генерации
        """
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else input_tokens + output_tokens

        # Получаем trace_id если доступны декораторы
        trace_id = None
        try:
            from langfuse.decorators import langfuse_context
            trace_id = langfuse_context.get_current_trace_id()
            logger.info("✅ Langfuse tracing with decorators completed")
        except ImportError:
            logger.info("✅ Basic Langfuse tracing completed")
        except Exception as e:
            logger.warning(f"⚠️ Failed to get trace ID: {e}")

        return {
            "profile": profile_json,
            "metadata": {
                "model": model,
                "generation_time": generation_time,
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "total": total_tokens,
                },
                "temperature": self.prompt_manager.get_prompt_config("profile_generation").get("temperature", 0.1),
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "langfuse_trace_id": trace_id,
                "prompt_name": prompt_name,
                "prompt_version": getattr(prompt_obj, "version", "local_fallback"),
                "prompt_source": "langfuse" if prompt_obj else "local_fallback",
                "tracing_mode": "decorator_based",
                "department": variables.get("department"),
                "position": variables.get("position"),
            },
            "raw_response": generated_text,
        }

    async def generate_profile_from_langfuse(
        self,
        prompt_name: str,
        variables: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        @doc Асинхронная генерация профиля должности через Langfuse prompt с traced execution

        Args:
            prompt_name: Имя промпта в Langfuse
            variables: Переменные для подстановки в промпт
            user_id: ID пользователя для трейсинга
            session_id: ID сессии для трейсинга

        Returns:
            Словарь с результатом генерации

        Examples:
            python>
            client = LLMClient(api_key, langfuse_keys...)
            result = await client.generate_profile_from_langfuse(
                prompt_name="a101-hr-profile-gemini-v2",
                variables={"position": "Senior Developer", "department": "IT"}
            )
        """
        start_time = time.time()

        try:
            # Получаем промпт и конфигурацию
            prompt_obj, config = await self._get_prompt_and_config_async(prompt_name)

            model = config.get("model", "google/gemini-2.5-flash")
            temperature = config.get("temperature", 0.1)
            max_tokens = config.get("max_tokens", 4000)
            response_format = config.get("response_format")

            logger.info(f"Starting generation with prompt: {prompt_name}")
            logger.info(f"Model: {model}, Temperature: {temperature}")

            # Компилируем промпт в формат messages
            messages = self._compile_prompt_to_messages(prompt_obj, variables)
            logger.info(f"Final messages count: {len(messages)}")

            # Строим метаданные для трейсинга
            trace_metadata = self._build_trace_metadata(
                prompt_name, prompt_obj, variables, user_id, session_id
            )

            # Выполняем асинхронный запрос с retry (только для транзиентных ошибок)
            response = None
            for attempt in range(LLM_MAX_RETRIES):
                try:
                    response = await self._create_generation_with_prompt(
                        prompt=prompt_obj,  # Может быть None при fallback
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        trace_metadata=trace_metadata,
                    )
                    logger.info("✅ Generation with prompt linking completed")
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as api_error:
                    retryable = self._is_retryable_exception(api_error)
                    is_last = attempt >= (LLM_MAX_RETRIES - 1)

                    if retryable and not is_last:
                        logger.warning(
                            "LLM request failed; retrying",
                            extra={
                                "attempt": attempt + 1,
                                "max_attempts": LLM_MAX_RETRIES,
                                "prompt_name": prompt_name,
                                "model": model,
                                "error_type": type(api_error).__name__,
                                "error": str(api_error)[:500],
                            },
                        )
                        await self._sleep_before_retry(attempt)
                        continue

                    logger.exception(
                        "LLM request failed",
                        extra={
                            "attempt": attempt + 1,
                            "max_attempts": LLM_MAX_RETRIES,
                            "prompt_name": prompt_name,
                            "model": model,
                            "error_type": type(api_error).__name__,
                        },
                    )
                    raise

            if response is None:
                raise RuntimeError("LLM request failed: no response after retries")

            # Извлекаем ответ и парсим JSON
            generated_text = response.choices[0].message.content
            profile_json = self._extract_and_parse_json(generated_text)

            generation_time = time.time() - start_time
            logger.info(f"Langfuse generation completed in {generation_time:.2f}s")

            # Строим и возвращаем успешный ответ
            return self._build_success_response(
                profile_json,
                generated_text,
                model,
                generation_time,
                response.usage,
                prompt_obj,
                prompt_name,
                variables,
            )

        except Exception as e:
            generation_time = time.time() - start_time
            logger.error(
                f"Langfuse generation failed after {generation_time:.2f}s: {e}"
            )

            # Получаем trace_id даже при ошибке (если доступно)
            try:
                from langfuse.decorators import langfuse_context

                trace_id = langfuse_context.get_current_trace_id()
            except (ImportError, NameError):
                trace_id = None

            return {
                "profile": None,
                "metadata": {
                    "model": "unknown",
                    "generation_time": generation_time,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                    "success": False,
                    "langfuse_trace_id": trace_id,
                },
                "raw_response": None,
            }

    def _extract_and_parse_json(self, generated_text: str) -> Dict[str, Any]:
        """Извлечение и парсинг JSON из ответа LLM"""
        try:
            # Ищем JSON в тексте (между ``` или в чистом виде)
            json_text = generated_text.strip()

            # Убираем markdown code blocks если есть
            if json_text.startswith("```"):
                json_text = json_text.split("```")[1]
                if json_text.startswith("json"):
                    json_text = json_text[4:]
                json_text = json_text.strip()

            if json_text.endswith("```"):
                json_text = json_text[:-3].strip()

            # Парсим JSON
            profile_data = json.loads(json_text)

            if not isinstance(profile_data, dict):
                raise ValueError("Response is not a JSON object")

            logger.info("JSON successfully parsed from LLM response")
            return profile_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Raw response text: {generated_text[:500]}...")

            # Возвращаем fallback структуру
            return {
                "error": "Failed to parse JSON from LLM response",
                "raw_response": generated_text,
                "parse_error": str(e),
            }

        except Exception as e:
            logger.error(f"Unexpected error while parsing response: {e}")
            return {
                "error": "Unexpected error during response parsing",
                "raw_response": generated_text,
                "parse_error": str(e),
            }

    def validate_profile_structure(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Валидация структуры сгенерированного профиля

        Returns:
            Словарь с результатами валидации
        """
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "completeness_score": 0.0,
        }

        # Проверяем обязательные поля (синхронизировано с новой схемой JSON)
        required_fields = [
            "position_title",
            "department_broad",
            "department_specific",
            "position_category",  # Переименовано с "category"
            "direct_manager",  # Новое поле
            "subordinates",  # Новое поле
            "primary_activity_type",  # Переименовано с "primary_activity"
            "responsibility_areas",
            "professional_skills",
            "corporate_competencies",  # Новое поле
            "personal_qualities",
            "experience_and_education",  # Новое поле
            "careerogram",  # Новое поле
            "workplace_provisioning",  # Новое поле
            "performance_metrics",  # Новое поле
            "additional_information",  # Новое поле
            "metadata",  # Новое поле
        ]

        missing_fields = []
        empty_fields = []
        total_fields = len(required_fields)
        filled_fields = 0

        # Валидация с поддержкой fallback для старых полей
        for field in required_fields:
            # Поддержка fallback для переименованных полей
            fallback_map = {
                "position_category": "category",
                "primary_activity_type": "primary_activity",
                "experience_and_education": "education",
                "careerogram": "career_path",
                "workplace_provisioning": "technical_requirements",
            }

            field_value = profile.get(field)
            # Если поле не найдено, проверяем fallback
            if field_value is None and field in fallback_map:
                field_value = profile.get(fallback_map[field])

            if field_value is None:
                missing_fields.append(field)
            elif not field_value or (
                isinstance(field_value, (list, dict)) and len(field_value) == 0
            ):
                empty_fields.append(field)
            else:
                filled_fields += 1

        if missing_fields:
            validation_result["is_valid"] = False
            validation_result["errors"].extend(
                [f"Missing required field: {field}" for field in missing_fields]
            )

        if empty_fields:
            validation_result["warnings"].extend(
                [f"Empty required field: {field}" for field in empty_fields]
            )

        # Подсчитываем полноту профиля
        validation_result["completeness_score"] = filled_fields / total_fields

        # Дополнительные проверки структуры для новых полей
        self._validate_responsibility_areas(profile, validation_result)
        self._validate_professional_skills(profile, validation_result)
        self._validate_subordinates(profile, validation_result)
        self._validate_careerogram(profile, validation_result)
        self._validate_performance_metrics(profile, validation_result)

        # Проверяем специфичные поля (legacy)
        if "basic_info" in profile and isinstance(profile["basic_info"], dict):
            basic_info = profile["basic_info"]
            if not basic_info.get("position_title"):
                validation_result["errors"].append(
                    "Missing position_title in basic_info"
                )

        logger.info(
            f"Profile validation completed: {validation_result['completeness_score']:.2%} complete, {len(validation_result['errors'])} errors"
        )

        return validation_result

    def _validate_responsibility_areas(
        self, profile: Dict[str, Any], validation_result: Dict[str, Any]
    ):
        """Валидация структуры областей ответственности"""
        if "responsibility_areas" in profile:
            areas = profile["responsibility_areas"]
            if isinstance(areas, list):
                for i, area in enumerate(areas):
                    if not isinstance(area, dict):
                        validation_result["warnings"].append(
                            f"Область ответственности {i+1} должна быть объектом"
                        )
                    else:
                        # Поддержка как старого формата (title), так и нового (area)
                        if "area" not in area and "title" not in area:
                            validation_result["warnings"].append(
                                f"Область ответственности {i+1} должна содержать 'area' или 'title'"
                            )
                        if "tasks" not in area:
                            validation_result["warnings"].append(
                                f"Область ответственности {i+1} должна содержать 'tasks'"
                            )

    def _validate_professional_skills(
        self, profile: Dict[str, Any], validation_result: Dict[str, Any]
    ):
        """Валидация структуры профессиональных навыков"""
        if "professional_skills" in profile:
            skills = profile["professional_skills"]
            if isinstance(skills, list):
                for i, skill_category in enumerate(skills):
                    if not isinstance(skill_category, dict):
                        validation_result["warnings"].append(
                            f"Категория навыков {i+1} должна быть объектом"
                        )
                    else:
                        # Проверка наличия skill_category или category (fallback)
                        if (
                            "skill_category" not in skill_category
                            and "category" not in skill_category
                        ):
                            validation_result["warnings"].append(
                                f"Категория навыков {i+1} должна содержать 'skill_category'"
                            )

                        # Проверка specific_skills или skills (fallback)
                        skills_field = skill_category.get(
                            "specific_skills", skill_category.get("skills")
                        )
                        if not skills_field:
                            validation_result["warnings"].append(
                                f"Категория навыков {i+1} должна содержать 'specific_skills'"
                            )
                        elif isinstance(skills_field, list) and len(skills_field) > 0:
                            # Проверяем структуру первого навыка для определения формата
                            first_skill = skills_field[0]
                            if isinstance(first_skill, dict):
                                # Новый формат с детальными навыками
                                for j, skill in enumerate(skills_field):
                                    required_skill_fields = [
                                        "skill_name",
                                        "proficiency_level",
                                        "proficiency_description",
                                    ]
                                    for field in required_skill_fields:
                                        if field not in skill:
                                            validation_result["warnings"].append(
                                                f"Навык {j+1} в категории {i+1} должен содержать '{field}'"
                                            )

    def _validate_subordinates(
        self, profile: Dict[str, Any], validation_result: Dict[str, Any]
    ):
        """Валидация структуры подчиненных"""
        if "subordinates" in profile:
            subordinates = profile["subordinates"]
            if isinstance(subordinates, dict):
                if "departments" not in subordinates:
                    validation_result["warnings"].append(
                        "Поле 'subordinates' должно содержать 'departments'"
                    )
                # Поддержка как direct_reports, так и people (fallback)
                if (
                    "direct_reports" not in subordinates
                    and "people" not in subordinates
                ):
                    validation_result["warnings"].append(
                        "Поле 'subordinates' должно содержать 'direct_reports'"
                    )

    def _validate_careerogram(
        self, profile: Dict[str, Any], validation_result: Dict[str, Any]
    ):
        """Валидация структуры карьерограммы"""
        # Поддержка и новой (careerogram) и старой (career_path) структуры
        careerogram = profile.get("careerogram") or profile.get("career_path")
        if careerogram and isinstance(careerogram, dict):
            # Проверка новой структуры career_pathways
            if "career_pathways" in careerogram:
                career_pathways = careerogram["career_pathways"]
                if isinstance(career_pathways, list):
                    for i, pathway in enumerate(career_pathways):
                        if not isinstance(pathway, dict):
                            validation_result["warnings"].append(
                                f"Карьерный путь {i+1} должен быть объектом"
                            )
                        else:
                            required_pathway_fields = [
                                "pathway_type",
                                "entry_positions",
                                "advancement_positions",
                            ]
                            for field in required_pathway_fields:
                                if field not in pathway:
                                    validation_result["warnings"].append(
                                        f"Карьерный путь {i+1} должен содержать '{field}'"
                                    )
            else:
                # Для старой структуры проверяем legacy поля
                legacy_fields = ["donor_positions", "target_positions"]
                missing_legacy = [
                    field for field in legacy_fields if field not in careerogram
                ]
                if missing_legacy:
                    validation_result["warnings"].append(
                        f"Карьерограмма должна содержать {missing_legacy}"
                    )

    def _validate_performance_metrics(
        self, profile: Dict[str, Any], validation_result: Dict[str, Any]
    ):
        """Валидация структуры метрик эффективности"""
        if "performance_metrics" in profile:
            metrics = profile["performance_metrics"]
            if isinstance(metrics, dict):
                required_fields = [
                    "quantitative_kpis",
                    "qualitative_indicators",
                    "evaluation_frequency",
                ]
                for field in required_fields:
                    if field not in metrics:
                        validation_result["warnings"].append(
                            f"performance_metrics должен содержать '{field}'"
                        )
