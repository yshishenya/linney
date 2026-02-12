"""
@doc
GeneratorComponent - Компонент генерации профилей должностей для Linney.

Единственная ответственность: управление процессом генерации профилей LLM.
Обрабатывает запуск генерации, отслеживание прогресса, отображение результатов и ошибок.

События:
- on_generation_complete(profile_data) - генерация успешно завершена
- on_generation_error(error_message) - произошла ошибка генерации

Examples:
  python> generator = GeneratorComponent(api_client)
  python> generator.on_generation_complete = viewer.show_profile
  python> await generator.render_generator_section()
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable

from nicegui import ui

try:
    # Relative imports для запуска как модуль
    try:
        from ...core.error_recovery import (
            ErrorRecoveryCoordinator,
            RetryConfig,
            CircuitBreakerConfig,
        )
    except ImportError:
        # Error recovery is optional - system can work without it
        ErrorRecoveryCoordinator = None
        RetryConfig = None
        CircuitBreakerConfig = None
except ImportError:
    try:
        # Docker imports с /app в PYTHONPATH
        from frontend.core.error_recovery import (
            ErrorRecoveryCoordinator,
            RetryConfig,
            CircuitBreakerConfig,
        )
    except ImportError:
        # Error recovery is optional - system can work without it
        ErrorRecoveryCoordinator = None
        RetryConfig = None
        CircuitBreakerConfig = None

logger = logging.getLogger(__name__)


class GeneratorComponent:
    """
    @doc
    Компонент генерации профилей должностей с LLM.

    Особенности:
    - Асинхронная генерация через OpenRouter API + Gemini 2.5 Flash
    - Real-time отслеживание прогресса генерации
    - Professional UI с прогресс-барами и спиннерами
    - Retry logic при ошибках генерации
    - События для интеграции с другими компонентами

    Examples:
      python> generator = GeneratorComponent(api_client)
      python> generator.on_generation_complete = lambda data: print("Done!")
      python> container = await generator.render_generator_section()
    """

    def __init__(
        self,
        api_client,
        error_recovery_coordinator: Optional[ErrorRecoveryCoordinator] = None,
    ):
        """
        @doc
        Инициализация компонента генерации профилей.

        Args:
            api_client: Экземпляр APIClient для взаимодействия с backend

        Examples:
          python> generator = GeneratorComponent(api_client)
          python> # Компонент готов к использованию
        """
        self.api_client = api_client
        self.error_recovery_coordinator = error_recovery_coordinator

        # UI компоненты
        self.generate_button = None
        self.progress_dialog = None
        self.generation_status_container = None

        # Состояние генерации
        self.is_generating = False
        self.current_task_id = None
        self.selected_position = ""
        self.selected_department = ""
        self.generation_attempts = 0
        self.last_generation_error = None
        self.recovery_mode = False

        # Error recovery components
        self.circuit_breaker = None
        self.retry_manager = None
        if self.error_recovery_coordinator:
            self.circuit_breaker = self.error_recovery_coordinator.get_circuit_breaker(
                "generator_component",
                CircuitBreakerConfig(failure_threshold=2, timeout_seconds=120),
            )
            self.retry_manager = self.error_recovery_coordinator.get_retry_manager(
                "generator_retry",
                RetryConfig(max_retries=2, base_delay=5, max_delay=60),
            )
            # Register recovery callback
            self.error_recovery_coordinator.register_recovery_callback(
                "generator_component", self._on_recovery_callback
            )

        # События для интеграции с другими компонентами
        self.on_generation_complete: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_generation_error: Optional[Callable[[str], None]] = None

    def set_position(self, position: str, department: str):
        """Sets the selected position and department for generation."""
        logger.info(
            f"🔥 DEBUG: GeneratorComponent.set_position called with position='{position}', department='{department}'"
        )
        self.selected_position = position
        self.selected_department = department
        self.generation_attempts = 0  # Reset attempts for new position
        self.last_generation_error = None

        # Save state for recovery
        if self.error_recovery_coordinator:
            self._save_component_state()

        # Обновляем UI состояние кнопки генерации
        self._update_generation_ui_state()

        logger.info(f"Generator received position: {position} in {department}")

    async def render_generator_section(self) -> ui.column:
        """Render the profile generation section."""
        with ui.column().classes("w-full gap-4") as generator_container:
            # Заголовок секции
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("auto_awesome", size="1.5rem").classes("text-primary")
                ui.label("Генерация профиля").classes(
                    "text-h6 text-weight-medium text-primary"
                )

            # Кнопка генерации с подсказкой
            self.generate_button = (
                ui.button(
                    "🚀 Сгенерировать профиль",
                    icon="auto_awesome",
                    on_click=self._start_generation,
                )
                .classes("w-full")
                .props("size=lg color=primary")
                .tooltip(
                    "Создать детальный профиль должности с помощью ИИ. Процесс займет 2-5 минут."
                )
            )

            # Изначально кнопка отключена до выбора позиции
            self.generate_button.set_enabled(False)

            # Подсказка для пользователей
            ui.label(
                "ℹ️ Выберите должность из поиска выше для активации генерации"
            ).classes("text-caption text-grey-6 mt-2 text-center")

            # Контейнер для статуса генерации
            self.generation_status_container = ui.column().classes("w-full")

        return generator_container

    def _update_generation_ui_state(self):
        """Update the UI state of the generation button.
        
        This method enables or disables the generate button based on the  presence of a
        selected position and department. If both are selected  and the generation
        process is not ongoing, the button is enabled with  the appropriate text. If
        the generation is in progress, the button  displays a loading message;
        otherwise, it shows the default text.
        """
        if self.generate_button:
            has_position = bool(self.selected_position and self.selected_department)

            if has_position and not self.is_generating:
                self.generate_button.set_enabled(True)
                self.generate_button.set_text(
                    f"🚀 Сгенерировать профиль: {self.selected_position}"
                )
            else:
                self.generate_button.set_enabled(False)
                if self.is_generating:
                    self.generate_button.set_text("⏳ Генерация...")
                else:
                    self.generate_button.set_text("🚀 Сгенерировать профиль")

    async def _start_generation(self):
        """Start the generation of a job profile.
        
        This method initiates the profile generation process by sending a request to
        the backend via an API call. It first checks if a position and department are
        selected, and if not, it notifies the user. Upon successful initiation, it
        updates the UI state, logs the generation data, and handles the response,
        including error management and progress display.
        """
        if (
            not self.selected_position
            or not self.selected_department
            or self.is_generating
        ):
            ui.notify("❌ Выберите позицию для генерации", type="warning")
            return

        try:
            self.is_generating = True
            if self.generate_button:
                self.generate_button.set_enabled(False)
            self._update_generation_ui_state()

            # Подготовка данных для генерации
            generation_data = {
                "department": self.selected_department,
                "position": self.selected_position,
                "save_result": True,
            }

            logger.info(f"Starting generation with data: {generation_data}")

            # Запуск генерации через API с улучшенной обработкой ошибок
            self.generation_attempts += 1
            response = await self._safe_generation_api_call(
                self.api_client.start_profile_generation, **generation_data
            )

            if not response:
                error_msg = "Failed to start generation after all retry attempts"
                await self._handle_generation_failure(error_msg, allow_retry=True)
                return

            if response.get("task_id") and response.get("status") == "queued":
                self.current_task_id = response["task_id"]
                message = response.get("message", "Генерация профиля запущена")
                ui.notify(f"🚀 {message}", type="positive", position="top")

                # Save successful state
                if self.error_recovery_coordinator:
                    self._save_component_state()

                # Показываем прогресс
                await self._show_generation_progress()
            else:
                error_msg = response.get("message", "Неизвестная ошибка")
                logger.error(f"Generation start failed: {error_msg}")
                await self._handle_generation_failure(error_msg, allow_retry=True)

        except Exception as e:
            logger.error(f"Unexpected error starting generation: {e}")
            await self._handle_generation_failure(
                f"Ошибка запуска: {str(e)}", allow_retry=True
            )
        finally:
            self.is_generating = False
            if self.generate_button:
                self.generate_button.set_enabled(True)
            self._update_generation_ui_state()

    async def _show_generation_progress(self):
        """
        @doc
        Отображение прогресса генерации в диалоге.

        Показывает прогресс-бар, статус и кнопку отмены генерации.

        Examples:
          python> await generator._show_generation_progress()
          python> # Показан диалог с прогрессом генерации
        """
        with ui.dialog() as dialog:
            dialog.on("close", self._cancel_generation)

            with ui.card().classes("min-w-[400px]"):
                with ui.card_section().classes("py-6 px-8"):
                    # Улучшенный заголовок с анимацией
                    with ui.row().classes("items-center gap-3 mb-4"):
                        ui.spinner(size="lg", color="primary").classes("animate-spin")
                        with ui.column().classes("gap-1"):
                            ui.label("🚀 Генерация профиля должности").classes(
                                "text-lg font-semibold text-primary"
                            )
                            progress_status = ui.label(
                                "Инициализация процесса..."
                            ).classes("text-sm text-blue-600")

                    # Улучшенная информация о позиции
                    with ui.card().classes("w-full bg-blue-50 mb-4"):
                        with ui.card_section().classes("py-3"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("work", size="sm").classes("text-blue-600")
                                ui.label(f"Позиция: {self.selected_position}").classes(
                                    "text-subtitle2 font-medium text-blue-900"
                                )
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("business", size="sm").classes("text-blue-600")
                                ui.label(
                                    f"Департамент: {self.selected_department}"
                                ).classes("text-body2 text-blue-700")

                    # Улучшенный прогресс-бар с анимацией
                    ui.label("Прогресс генерации:").classes(
                        "text-subtitle2 font-medium mb-2"
                    )
                    progress_bar = ui.linear_progress(value=0).classes("w-full mb-2")
                    progress_percentage = ui.label("0%").classes(
                        "text-xs text-blue-600 text-right"
                    )

                    # Индикатор времени
                    estimated_time = ui.label("⏱️ Ожидаемое время: 2-5 минут").classes(
                        "text-caption text-grey-6 mb-4"
                    )

                    # Этапы генерации
                    with ui.expansion("📋 Этапы генерации", icon="info").classes(
                        "w-full mb-4"
                    ):
                        with ui.column().classes("gap-1"):
                            ui.label("1. 🔍 Анализ должности и департамента").classes(
                                "text-caption"
                            )
                            ui.label("2. 🤖 Генерация контента с помощью ИИ").classes(
                                "text-caption"
                            )
                            ui.label(
                                "3. ✅ Валидация и структурирование данных"
                            ).classes("text-caption")
                            ui.label("4. 💾 Сохранение готового профиля").classes(
                                "text-caption"
                            )

                    # Кнопка отмены с предупреждением
                    with ui.row().classes("justify-center mt-6"):
                        ui.button(
                            "Отменить генерацию", icon="cancel", on_click=dialog.close
                        ).props("outlined color=orange").tooltip(
                            "Прервать процесс генерации. Частично созданный профиль будет потерян."
                        )

        self.progress_dialog = dialog
        dialog.open()

        # Отслеживание прогресса
        await self._poll_generation_status(
            dialog, progress_status, progress_bar, progress_percentage
        )

    async def _poll_generation_status(
        self, dialog, status_label, progress_bar, progress_percentage
    ):
        """
        @doc
        Опрос статуса генерации каждые 5 секунд.

        Обновляет прогресс-бар и статус до завершения генерации.

        Args:
            dialog: Диалог прогресса
            status_label: Лейбл текущего статуса
            progress_bar: Прогресс-бар
            progress_percentage: Лейбл процентов

        Examples:
          python> await generator._poll_generation_status(dialog, status, bar, pct)
          python> # Статус отслеживается до завершения
        """
        max_attempts = 60  # 5 минут максимум
        attempt = 0

        while (
            attempt < max_attempts and dialog.value
        ):  # Проверяем, что диалог не закрыт
            try:
                status_response = await self.api_client.get_generation_task_status(
                    self.current_task_id
                )

                if not status_response.get("success"):
                    logger.warning(f"Status check failed: {status_response}")
                    # Показываем предупреждение в UI но продолжаем попытки
                    status_label.text = "Проблемы с проверкой статуса..."
                    await asyncio.sleep(5)
                    attempt += 1
                    continue

                task_data = status_response["task"]
                status = task_data["status"]
                progress = task_data.get("progress", 0)
                current_step = task_data.get("current_step", "Обработка...")

                # Обновляем UI с улучшенной информацией
                status_emoji_map = {
                    "Анализ": "🔍",
                    "Генерация": "🤖",
                    "Валидация": "✅",
                    "Сохранение": "💾",
                    "Обработка": "⚙️",
                    "Завершение": "🎉",
                }

                # Добавляем эмодзи к статусу
                enhanced_status = current_step
                for key, emoji in status_emoji_map.items():
                    if key.lower() in current_step.lower():
                        enhanced_status = f"{emoji} {current_step}"
                        break

                status_label.text = enhanced_status
                progress_bar.value = progress / 100.0
                progress_percentage.text = f"{progress}% завершено"

                if status == "completed":
                    dialog.close()
                    # Reset error state on success
                    self.generation_attempts = 0
                    self.last_generation_error = None
                    self.recovery_mode = False
                    await self._show_generation_success()
                    break
                elif status == "failed":
                    dialog.close()
                    error_msg = task_data.get("error_message", "Неизвестная ошибка")
                    await self._handle_generation_failure(error_msg, allow_retry=True)
                    break
                elif status == "cancelled":
                    dialog.close()
                    ui.notify("Генерация отменена", type="warning")
                    break

                await asyncio.sleep(5)  # Проверяем каждые 5 секунд
                attempt += 1

            except Exception as e:
                logger.error(f"Error polling generation status: {e}")
                # Enhanced status check error handling
                if self._should_retry_status_check(e, attempt):
                    status_label.text = f"Проблемы с проверкой статуса, повторяем..."
                    await asyncio.sleep(
                        min(5 * (attempt // 5 + 1), 30)
                    )  # Progressive delay
                    attempt += 1
                else:
                    # Give up on status checks - assume generation failed
                    dialog.close()
                    await self._handle_generation_failure(
                        f"Не удалось отследить статус генерации: {str(e)}",
                        allow_retry=True,
                    )
                    break

        if attempt >= max_attempts:
            dialog.close()
            await self._handle_generation_failure(
                "Превышено время ожидания генерации", allow_retry=True
            )

    async def _show_generation_success(self):
        # Получаем результат генерации с обработкой ошибок
        """Displays a success dialog for the generation completion."""
        try:
            result_response = await self.api_client.get_generation_task_result(
                self.current_task_id
            )
        except Exception as e:
            logger.error(f"Error fetching generation result: {e}")
            await self._show_generation_error(f"Ошибка получения результата: {str(e)}")
            return

        with ui.dialog() as dialog:
            with ui.card().classes("text-center p-6"):
                with ui.card_section().classes("text-center py-8"):
                    # Иконка успеха
                    ui.icon("check_circle", size="4rem").classes("text-success mb-4")

                    # Заголовок
                    ui.label("🎉 Профиль успешно создан!").classes(
                        "text-2xl font-bold text-success mb-2"
                    )
                    ui.label(
                        f"Профиль должности '{self.selected_position}' готов для использования"
                    ).classes("text-muted mb-6")

                    # Действия
                    with ui.row().classes("gap-3 justify-center"):
                        ui.button(
                            "Просмотреть профиль",
                            icon="description",
                            on_click=lambda: self._view_profile_result(
                                result_response, dialog
                            ),
                        ).props("color=primary")

                        ui.button(
                            "Создать еще один",
                            icon="add",
                            on_click=lambda: self._create_another(dialog),
                        ).props("outlined")

        dialog.open()

        # Вызываем событие для других компонентов
        if self.on_generation_complete and result_response:
            self.on_generation_complete(result_response)

        ui.notify("✅ Профиль успешно сгенерирован!", type="positive", position="top")

    async def _show_generation_error(self, error_message: str):
        """
        @doc
        Отображение ошибки генерации с user-friendly сообщениями.

        Показывает диалог ошибки с возможностью повтора генерации.

        Args:
            error_message: Техническое сообщение об ошибке

        Examples:
          python> await generator._show_generation_error("Timeout error")
          python> # Показан диалог ошибки с кнопкой повтора
        """
        # Convert technical errors to user-friendly messages
        friendly_message, suggestion = self._get_user_friendly_error(error_message)

        with ui.dialog() as dialog:
            with ui.card().classes("border-l-4 border-orange-500 bg-orange-50"):
                with ui.card_section().classes("py-6"):
                    # Заголовок ошибки
                    with ui.row().classes("items-center gap-3 mb-4"):
                        ui.icon("warning", size="2rem").classes("text-orange-600")
                        ui.label("⚠️ Не удалось создать профиль").classes(
                            "text-lg font-bold text-orange-800"
                        )

                    # User-friendly сообщение об ошибке
                    ui.label(friendly_message).classes(
                        "text-body1 text-orange-700 mb-3"
                    )

                    # Предложение по решению
                    if suggestion:
                        ui.label(suggestion).classes("text-body2 text-orange-600 mb-4")

                    # Технические детали (сворачиваемые)
                    with ui.expansion("🔧 Технические детали", icon="info").classes(
                        "w-full mb-4"
                    ):
                        ui.label(error_message).classes(
                            "text-caption font-mono bg-grey-100 p-2 rounded"
                        )

                    # Действия
                    with ui.row().classes("gap-3"):
                        ui.button(
                            "Попробовать еще раз",
                            icon="refresh",
                            on_click=lambda: self._retry_generation(dialog),
                        ).props("color=orange-6")

                        ui.button(
                            "Выбрать другую должность",
                            icon="search",
                            on_click=lambda: self._select_different_position(dialog),
                        ).props("outlined color=orange-6")

                        ui.button("Закрыть", on_click=dialog.close).props("outlined")

        dialog.open()

        # Вызываем событие для других компонентов
        if self.on_generation_error:
            self.on_generation_error(error_message)

        ui.notify(f"⚠️ {friendly_message}", type="warning", position="top")

    def _get_user_friendly_error(self, technical_error: str) -> tuple[str, str]:
        """Convert technical error messages into user-friendly messages.
        
        This function analyzes the provided technical error message and maps it to a
        more understandable message for the user, along with a suggestion for
        resolution. It checks for various categories of errors, including network
        issues, API errors, rate limits, authorization problems, generation failures,
        and validation errors, returning appropriate messages based on the identified
        issue.
        
        Args:
            technical_error (str): A technical error message.
        
        Returns:
            tuple[str, str]: A tuple containing a user-friendly message and a suggestion for resolution.
        """
        error_lower = technical_error.lower()

        # Network and API errors
        if any(
            keyword in error_lower for keyword in ["timeout", "connection", "network"]
        ):
            return (
                "🌐 Проблема с подключением к серверу",
                "Проверьте интернет-соединение и попробуйте еще раз через минуту",
            )

        elif any(
            keyword in error_lower
            for keyword in ["api", "server error", "500", "502", "503"]
        ):
            return (
                "⚙️ Сервер временно недоступен",
                "Наши серверы испытывают проблемы. Попробуйте через несколько минут",
            )

        elif any(keyword in error_lower for keyword in ["rate limit", "429", "quota"]):
            return (
                "⏰ Превышен лимит запросов",
                "Подождите немного перед следующей попыткой генерации",
            )

        elif any(keyword in error_lower for keyword in ["unauthorized", "401", "auth"]):
            return (
                "🔐 Проблема с авторизацией",
                "Войдите в систему заново или обратитесь к администратору",
            )

        # Generation specific errors
        elif any(
            keyword in error_lower for keyword in ["generation failed", "model error"]
        ):
            return (
                "🤖 ИИ не смог создать профиль",
                "Попробуйте еще раз или выберите другую должность для генерации",
            )

        elif "превышено время ожидания" in error_lower:
            return (
                "⏱️ Генерация заняла слишком много времени",
                "Попробуйте создать профиль еще раз. Некоторые должности требуют больше времени",
            )

        # Validation errors
        elif any(keyword in error_lower for keyword in ["validation", "invalid"]):
            return (
                "📝 Ошибка в данных должности",
                "Проверьте правильность названия должности и департамента",
            )

        # Generic fallback
        else:
            return (
                "❌ Произошла неожиданная ошибка",
                "Попробуйте еще раз или выберите другую должность. Если проблема повторяется, обратитесь в поддержку",
            )

    def _select_different_position(self, dialog):
        """Closes the error dialog and prompts to select a different position."""
        dialog.close()
        self._reset_generator()
        ui.notify("🔍 Выберите другую должность для генерации", type="info")

    def _view_profile_result(self, result, dialog):
        """View the generated profile result.
        
        Args:
            result: Profile data from the API.
            dialog: Dialog for closing.
        """
        dialog.close()

        # Вызываем событие для компонента просмотра профилей
        if self.on_generation_complete and result:
            self.on_generation_complete(result)

    def _create_another(self, dialog):
        """
        @doc
        Создание еще одного профиля.

        Закрывает диалог успеха и сбрасывает состояние генератора.

        Args:
            dialog: Диалог для закрытия

        Examples:
          python> generator._create_another(dialog)
          python> # Генератор готов к новой генерации
        """
        dialog.close()
        self._reset_generator()

    def _retry_generation(self, dialog):
        """
        @doc
        Повтор генерации после ошибки.

        Args:
            dialog: Диалог ошибки для закрытия

        Examples:
          python> generator._retry_generation(dialog)
          python> # Запущен повтор генерации
        """
        dialog.close()
        asyncio.create_task(self._start_generation())

    def _reset_generator(self):
        """Resets the generator state."""
        self.selected_position = ""
        self.selected_department = ""
        self.current_task_id = None
        self.is_generating = False

        # Обновляем UI
        self._update_generation_ui_state()

        # Очищаем контейнер статуса
        if self.generation_status_container:
            self.generation_status_container.clear()

        ui.notify("🔄 Генератор сброшен", type="info")

    def _cancel_generation(self):
        """
        @doc
        Отмена текущей генерации.

        Закрывает диалог прогресса и отменяет задачу на backend.

        Examples:
          python> generator._cancel_generation()
          python> # Генерация отменена
        """
        if self.progress_dialog:
            self.progress_dialog.close()

        if self.current_task_id:
            # Асинхронно отменяем задачу на backend
            asyncio.create_task(self._cancel_backend_task())

        self.current_task_id = None
        self.is_generating = False
        self._update_generation_ui_state()

        ui.notify("Генерация отменена", type="warning")

    async def _cancel_backend_task(self):
        """
        @doc
        Отмена задачи на backend.

        Отправляет запрос отмены текущей задачи генерации.

        Examples:
          python> await generator._cancel_backend_task()
          python> # Задача отменена на backend
        """
        if self.current_task_id:
            try:
                await self.api_client.cancel_generation_task(self.current_task_id)
                logger.info(f"Cancelled generation task: {self.current_task_id}")
            except Exception as e:
                logger.error(f"Error cancelling generation task: {e}")
                # Показываем уведомление пользователю о проблеме с отменой
                ui.notify(
                    "⚠️ Не удалось отменить задачу на сервере. Возможно, она уже завершена.",
                    type="warning",
                    position="top",
                )

    def get_generation_status(self) -> Dict[str, Any]:
        """Retrieve the current generation status."""
        return {
            "is_generating": self.is_generating,
            "task_id": self.current_task_id,
            "selected_position": self.selected_position,
            "selected_department": self.selected_department,
            "generation_attempts": self.generation_attempts,
            "recovery_mode": self.recovery_mode,
            "last_error": self.last_generation_error,
        }

    # === Error Recovery Methods ===

    async def _safe_generation_api_call(self, api_func, *args, **kwargs):
        """Execute generation API call with circuit breaker and retry protection.
        
        This function attempts to call the specified API function with the provided
        arguments. If the circuit breaker and retry manager are not available, it
        falls back to a direct call. In case of an exception during the call, it  logs
        the error and returns None. When the recovery infrastructure is in  place, it
        utilizes the circuit breaker and retry manager to handle errors  and retries
        based on the defined conditions.
        
        Args:
            api_func: API function to call
            *args: Positional arguments for api_func
            **kwargs: Keyword arguments for api_func
        """
        if not self.circuit_breaker or not self.retry_manager:
            # Fallback to direct call if no recovery infrastructure
            try:
                return await api_func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Direct generation API call failed: {e}")
                return None

        try:
            # Use circuit breaker with retry manager for generation calls
            return await self.circuit_breaker.call(
                self.retry_manager.retry,
                api_func,
                *args,
                retry_condition=self._should_retry_generation_error,
                **kwargs,
            )
        except Exception as e:
            logger.error(
                f"Safe generation API call failed after all recovery attempts: {e}"
            )
            self.last_generation_error = str(e)
            return None

    def _should_retry_generation_error(self, error: Exception) -> bool:
        """Determine if generation error should trigger retry.
        
        This function evaluates the provided error to decide if a retry is warranted.
        It first checks against a list of permanent errors that should not trigger a
        retry.  If the error is not permanent, it then checks for conditions that
        indicate a temporary  issue, which would allow for a retry. Debug logging is
        performed to provide insights  into the decision-making process.
        """
        error_str = str(error).lower()

        # Don't retry certain permanent errors
        permanent_errors = [
            "invalid position",
            "invalid department",
            "not found",
            "authorization",
            "permission denied",
            "quota exceeded",
            "validation error",
            "bad request",
            "400",
            "401",
            "403",
            "404",
        ]

        if any(perm_error in error_str for perm_error in permanent_errors):
            logger.debug(f"Generation error is permanent, not retrying: {error}")
            return False

        # Retry on temporary/network errors
        retry_conditions = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "502",
            "503",
            "504",
            "service unavailable",
            "rate limit",
            "too many requests",
            "server error",
            "generation failed",
            "model error",
            "llm error",
        ]

        should_retry = any(condition in error_str for condition in retry_conditions)

        if should_retry:
            logger.debug(f"Generation error is retryable: {error}")
        else:
            logger.debug(f"Generation error is not retryable: {error}")

        return should_retry

    def _should_retry_status_check(self, error: Exception, attempt: int) -> bool:
        # Give up after too many attempts
        """Determine if status check error should be retried.
        
        Args:
            error: Exception from status check.
            attempt: Current attempt number.
        
        Returns:
            True if the status check should be retried, otherwise False.
        """
        if attempt >= 20:  # 20 attempts = ~15 minutes with progressive delays
            return False

        error_str = str(error).lower()

        # Always retry network/connection issues for status checks
        network_errors = [
            "timeout",
            "connection",
            "network",
            "unreachable",
            "502",
            "503",
            "504",
            "service unavailable",
        ]

        return any(net_error in error_str for net_error in network_errors)

    async def _handle_generation_failure(
        self, error_message: str, allow_retry: bool = True
    ):
        """Handle generation failure and provide recovery options.
        
        Args:
            error_message: Error message from the failure.
            allow_retry: Whether to offer retry options to user.
        """
        self.last_generation_error = error_message
        logger.error(f"Generation failure: {error_message}")

        # Report to error recovery coordinator
        if self.error_recovery_coordinator:
            try:
                error = Exception(f"generation_failure: {error_message}")
                recovered = (
                    await self.error_recovery_coordinator.handle_component_error(
                        "generator_component", error, attempt_recovery=True
                    )
                )

                if recovered:
                    logger.info("Generator component recovery successful")
                    ui.notify(
                        "🔄 Генератор восстановлен, попробуйте еще раз", type="positive"
                    )
                    return
            except Exception as recovery_error:
                logger.error(
                    f"Generator error recovery coordination failed: {recovery_error}"
                )

        # Show enhanced error dialog with recovery options
        await self._show_generation_error_with_recovery(error_message, allow_retry)

    async def _show_generation_error_with_recovery(
        self, error_message: str, allow_retry: bool = True
    ):
        # Convert technical errors to user-friendly messages
        """Show generation error with enhanced recovery options.
        
        This asynchronous function displays a user-friendly error dialog when a
        generation error occurs. It converts technical error messages into more
        understandable formats and provides suggestions for recovery. The dialog
        includes information about the number of attempts made, the current recovery
        mode status, and options for retrying or selecting a different position.
        
        Args:
            error_message (str): Technical error message.
            allow_retry (bool?): Whether to show retry options. Defaults to True.
        """
        friendly_message, suggestion = self._get_user_friendly_error(error_message)

        with ui.dialog() as dialog:
            with ui.card().classes(
                "border-l-4 border-orange-500 bg-orange-50 min-w-[500px]"
            ):
                with ui.card_section().classes("py-6"):
                    # Enhanced header with attempt info
                    with ui.row().classes("items-center gap-3 mb-4"):
                        ui.icon("warning", size="2rem").classes("text-orange-600")
                        with ui.column().classes("gap-1"):
                            ui.label("⚠️ Не удалось создать профиль").classes(
                                "text-lg font-bold text-orange-800"
                            )
                            if self.generation_attempts > 1:
                                ui.label(f"Попытка {self.generation_attempts}").classes(
                                    "text-caption text-orange-600"
                                )

                    # User-friendly error message
                    ui.label(friendly_message).classes(
                        "text-body1 text-orange-700 mb-3"
                    )

                    # Enhanced suggestion with recovery context
                    if suggestion:
                        ui.label(suggestion).classes("text-body2 text-orange-600 mb-4")

                    # Show generation attempts and recovery status
                    if self.generation_attempts > 1 or self.recovery_mode:
                        with ui.card().classes(
                            "w-full bg-blue-50 border border-blue-200 mb-4"
                        ):
                            with ui.card_section().classes("py-3"):
                                if self.recovery_mode:
                                    ui.label("🔄 Режим восстановления активен").classes(
                                        "text-subtitle2 font-medium text-blue-800"
                                    )
                                ui.label(
                                    f"📊 Выполнено попыток: {self.generation_attempts}"
                                ).classes("text-body2 text-blue-700")

                    # Technical details (expandable)
                    with ui.expansion("🔧 Технические детали", icon="info").classes(
                        "w-full mb-4"
                    ):
                        ui.label(error_message).classes(
                            "text-caption font-mono bg-grey-100 p-2 rounded"
                        )

                        # Show circuit breaker status if available
                        if self.circuit_breaker:
                            stats = self.circuit_breaker.get_stats()
                            ui.label(
                                f"Circuit Breaker: {stats['state']} (failures: {stats['failure_count']})"
                            ).classes("text-caption text-grey-6 mt-2")

                    # Enhanced action buttons with conditions
                    with ui.row().classes("gap-3"):
                        if allow_retry and self.generation_attempts < 3:
                            # Smart retry with exponential backoff indicator
                            retry_delay = min(10 * self.generation_attempts, 60)
                            ui.button(
                                f"Повторить попытку (через {retry_delay}с)",
                                icon="refresh",
                                on_click=lambda: self._enhanced_retry_generation(
                                    dialog, retry_delay
                                ),
                            ).props("color=orange-6")
                        elif allow_retry:
                            # Reset and retry option after multiple failures
                            ui.button(
                                "Сбросить и попробовать заново",
                                icon="restart_alt",
                                on_click=lambda: self._reset_and_retry(dialog),
                            ).props("color=orange-6")

                        ui.button(
                            "Выбрать другую должность",
                            icon="search",
                            on_click=lambda: self._select_different_position(dialog),
                        ).props("outlined color=orange-6")

                        ui.button("Закрыть", on_click=dialog.close).props("outlined")

        dialog.open()

        # Call original error event for backward compatibility
        if self.on_generation_error:
            self.on_generation_error(error_message)

    async def _enhanced_retry_generation(self, dialog, delay_seconds: int):
        """Enhanced retry mechanism with user feedback and delay.
        
        Args:
            dialog: Error dialog to close.
            delay_seconds: Delay before retry.
        """
        dialog.close()
        self.recovery_mode = True

        # Show delay countdown
        with ui.dialog() as delay_dialog:
            with ui.card().classes("text-center p-6"):
                ui.label("🔄 Подготовка к повтору").classes("text-h6 font-medium mb-4")
                countdown_label = ui.label(
                    f"Повтор через {delay_seconds} секунд"
                ).classes("text-body1")

                progress_bar = ui.linear_progress(value=0).classes("w-full mt-4")

                ui.button("Отменить", on_click=delay_dialog.close).props("outlined")

        delay_dialog.open()

        # Countdown with cancellation check
        for remaining in range(delay_seconds, 0, -1):
            if not delay_dialog.value:  # Dialog was closed
                return

            countdown_label.text = f"Повтор через {remaining} секунд"
            progress_bar.value = (delay_seconds - remaining) / delay_seconds
            await asyncio.sleep(1)

        if delay_dialog.value:  # Dialog still open
            delay_dialog.close()
            await self._start_generation()

    async def _reset_and_retry(self, dialog):
        """Reset the generator state and retry generation."""
        dialog.close()

        logger.info("Resetting generator state for fresh retry")

        # Reset error state
        self.generation_attempts = 0
        self.last_generation_error = None
        self.recovery_mode = False
        self.current_task_id = None

        # Clear circuit breaker if available
        if self.circuit_breaker:
            # Force reset circuit breaker state
            self.circuit_breaker._reset()

        ui.notify("🔄 Генератор сброшен, начинаем заново", type="info")

        # Small delay then retry
        await asyncio.sleep(2)
        await self._start_generation()

    def _save_component_state(self):
        """Save the current component state for recovery."""
        if not self.error_recovery_coordinator:
            return

        state_data = {
            "selected_position": self.selected_position,
            "selected_department": self.selected_department,
            "is_generating": self.is_generating,
            "current_task_id": self.current_task_id,
            "generation_attempts": self.generation_attempts,
            "recovery_mode": self.recovery_mode,
            "last_generation_error": self.last_generation_error,
            "timestamp": time.time(),
        }

        try:
            self.error_recovery_coordinator.state_manager.save_state(
                "generator_component", state_data, ttl_seconds=1800  # 30 minute TTL
            )
            logger.debug("Generator component state saved for recovery")
        except Exception as e:
            logger.error(f"Failed to save generator component state: {e}")

    async def _on_recovery_callback(self, recovered_state: Dict[str, Any]):
        """
        @doc
        Handle state recovery from error recovery coordinator.

        Args:
            recovered_state: Previously saved state data

        Examples:
          python> await generator._on_recovery_callback({"selected_position": "Developer"})
          python> # Generator state recovered from coordinator
        """
        try:
            logger.info("Recovering generator component state...")

            # Restore state data
            self.selected_position = recovered_state.get("selected_position", "")
            self.selected_department = recovered_state.get("selected_department", "")
            self.generation_attempts = recovered_state.get("generation_attempts", 0)
            self.last_generation_error = recovered_state.get("last_generation_error")
            self.recovery_mode = True

            # Don't restore active generation state to avoid conflicts
            self.is_generating = False
            self.current_task_id = None

            # Update UI
            self._update_generation_ui_state()

            ui.notify("🔄 Генератор восстановлен после ошибки", type="positive")
            logger.info("Generator component state recovery completed")

        except Exception as e:
            logger.error(f"Error during generator state recovery: {e}")
            ui.notify("⚠️ Частичное восстановление генератора", type="warning")

    async def reset_component_state(self):
        """Reset the component to a clean state."""
        logger.info("Resetting generator component state")

        # Clear all generation state
        self.is_generating = False
        self.current_task_id = None
        self.selected_position = ""
        self.selected_department = ""
        self.generation_attempts = 0
        self.last_generation_error = None
        self.recovery_mode = False

        # Close any open dialogs
        if self.progress_dialog:
            self.progress_dialog.close()

        # Reset circuit breaker if available
        if self.circuit_breaker:
            self.circuit_breaker._reset()

        # Update UI
        self._update_generation_ui_state()

        # Clear status container
        if self.generation_status_container:
            self.generation_status_container.clear()

        ui.notify("🔄 Генератор сброшен", type="info")
