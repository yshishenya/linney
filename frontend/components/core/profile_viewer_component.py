"""
@doc
ProfileViewerComponent - Компонент просмотра сгенерированных профилей.

Использует ui.refreshable для динамического обновления контента.
Отображает детальную информацию о профилях должностей встроенно.
Показывает содержимое профилей, метаданные генерации, версии.

События:
- on_download_request(profile_id, format) - запрос на скачивание

Examples:
  python> viewer = ProfileViewerComponent(api_client)
  python> viewer.on_download_request = files_manager.download_file
  python> viewer.show_profile(profile_data)
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from nicegui import ui

try:
    # Relative imports для запуска как модуль
    try:
        from ...core.error_recovery import ErrorRecoveryCoordinator, ManagedResource
    except ImportError:
        # Error recovery is optional - system can work without it
        ErrorRecoveryCoordinator = None
        ManagedResource = None
except ImportError:
    try:
        # Docker imports с /app в PYTHONPATH
        from frontend.core.error_recovery import (
            ErrorRecoveryCoordinator,
            ManagedResource,
        )
    except ImportError:
        # Error recovery is optional - system can work without it
        ErrorRecoveryCoordinator = None
        ManagedResource = None

logger = logging.getLogger(__name__)


class ProfileViewerComponent:
    """
    @doc
    Компонент просмотра детальной информации о профилях должностей.

    Особенности:
    - ui.refreshable для динамического обновления
    - Детальное отображение содержимого профилей JSON
    - Метаданные генерации LLM (токены, время, модель)
    - История версий профилей
    - Форматирование профессиональных навыков и задач
    - События для интеграции со скачиванием файлов

    Examples:
      python> viewer = ProfileViewerComponent(api_client)
      python> viewer.on_download_request = lambda pid, fmt: print("Download")
      python> viewer.show_profile({"profile_id": "123", ...})
    """

    def __init__(
        self,
        api_client,
        error_recovery_coordinator: Optional[ErrorRecoveryCoordinator] = None,
    ):
        """
        @doc
        Инициализация компонента просмотра профилей.

        Args:
            api_client: Экземпляр APIClient для взаимодействия с backend

        Examples:
          python> viewer = ProfileViewerComponent(api_client)
          python> # Компонент готов к использованию
        """
        self.api_client = api_client
        self.error_recovery_coordinator = error_recovery_coordinator

        # Состояние компонента
        self.current_profile = None
        self.profiles_list = []
        self.show_detailed_view = False
        self.is_corrupted = False
        self.recovery_mode = False

        # Новые поля для табированного интерфейса
        self.current_tab = "content"
        self.available_tabs = ["content", "metadata", "versions", "markdown"]
        self.markdown_cache = {}
        self.loading_states = {}

        # Resource management
        self.managed_resources = set()
        self.temp_data_cache = {}  # For temporary data that needs cleanup

        # Error recovery setup
        if self.error_recovery_coordinator:
            # Register recovery callback
            self.error_recovery_coordinator.register_recovery_callback(
                "profile_viewer_component", self._on_recovery_callback
            )

        # События для интеграции с другими компонентами
        self.on_download_request: Optional[Callable[[str, str], None]] = None
        self.on_tab_switch: Optional[Callable[[str], None]] = None

    def render_profile_viewer(self) -> ui.column:
        """
        @doc
        Рендеринг контейнера для просмотра профилей.

        Returns:
            ui.column: Контейнер для отображения профилей

        Examples:
          python> container = viewer.render_profile_viewer()
          python> # Контейнер просмотра профилей готов
        """
        with ui.column().classes("w-full gap-4") as profile_container:
            # Заголовок секции
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("preview", size="1.5rem").classes("text-primary")
                ui.label("Просмотр профилей").classes(
                    "text-h6 text-weight-medium text-primary"
                )

            # Контейнер для содержимого профилей (refreshable)
            self._render_profile_content()

        return profile_container

    @ui.refreshable
    def _render_profile_content(self):
        """
        @doc
        Рендеринг refreshable содержимого профилей.

        Показывает либо список профилей, либо детальный вид профиля.

        Examples:
          python> viewer._render_profile_content()
          python> # Отрендерен refreshable контент
        """
        with ui.column().classes("w-full"):
            if self.show_detailed_view and self.current_profile:
                self._render_detailed_profile_view()
            elif self.profiles_list:
                self._render_profiles_list()
            else:
                self._render_empty_state()

    def _render_empty_state(self):
        """Render the empty state UI."""
        with ui.card().classes("w-full p-8"):
            with ui.column().classes("items-center gap-4"):
                ui.icon("preview", size="3rem").classes("text-grey-5")
                ui.label("Нет профилей для отображения").classes("text-h6 text-grey-6")
                ui.label("Сгенерируйте профиль или выберите из списка").classes(
                    "text-body2 text-grey-5"
                )

    def _render_profiles_list(self):
        """Render a list of profiles with enhanced UX design."""
        ui.label(f"Найдено профилей: {len(self.profiles_list)}").classes("text-h6 mb-4")

        # Показываем до 10 профилей с улучшенным дизайном
        for profile in self.profiles_list[:10]:
            self._render_enhanced_profile_card(profile)

    def _render_enhanced_profile_card(self, profile):
        """Renders an enhanced profile card with modern UX design."""
        status = profile.get("status", "completed")
        position = profile.get(
            "position", profile.get("position_title", "Неизвестная должность")
        )
        department = profile.get("department", profile.get("department_path", ""))
        created_at = profile.get("created_at")
        profile_id = profile.get("profile_id")

        with ui.card().classes(
            "w-full mb-3 hover:shadow-lg transition-shadow duration-200 border border-gray-200"
        ):
            with ui.card_section().classes("p-4"):
                # Main content area with improved hierarchy
                with ui.row().classes("w-full items-start gap-4"):

                    # Status indicator column (compact)
                    with ui.column().classes("items-center gap-1 min-w-fit"):
                        self._render_status_indicator(status)

                    # Profile information column (primary focus)
                    with ui.column().classes("flex-1 gap-2 min-w-0"):
                        # Position title - primary information
                        ui.label(position).classes(
                            "text-lg font-medium text-gray-900 leading-tight"
                        ).style("word-break: break-word")

                        # Department path - secondary information
                        if department:
                            self._render_compact_department_path(department)

                        # Metadata - tertiary information
                        if created_at:
                            formatted_date = self._format_datetime(created_at)
                            ui.label(f"Создан: {formatted_date}").classes(
                                "text-xs text-gray-500"
                            )

                    # Actions column (right-aligned)
                    with ui.column().classes("items-end gap-2 min-w-fit"):
                        # Primary action
                        ui.button(
                            "Просмотр профиля",
                            icon="visibility",
                            on_click=lambda p=profile: self.show_profile(p),
                        ).props("color=primary").classes("min-w-[140px]")

                        # Secondary actions - download menu
                        if profile_id:
                            self._render_profile_download_menu(profile_id)

    def _render_status_indicator(self, status: str):
        """Render a semantic status indicator for the profile.
        
        Args:
            status: The status of the profile.
        """
        status_config = {
            "completed": {
                "color": "bg-green-500",
                "text": "Готов",
                "tooltip": "Профиль готов к использованию",
            },
            "draft": {
                "color": "bg-amber-500",
                "text": "Черновик",
                "tooltip": "Профиль в разработке",
            },
            "in_progress": {
                "color": "bg-blue-500",
                "text": "В работе",
                "tooltip": "Профиль генерируется",
            },
            "error": {
                "color": "bg-red-500",
                "text": "Ошибка",
                "tooltip": "Требует внимания",
            },
        }

        config = status_config.get(status, status_config["completed"])

        # Status dot
        ui.html(f'<div class="w-2 h-2 rounded-full {config["color"]}"></div>')

        # Status text (compact)
        ui.label(config["text"]).classes("text-xs text-gray-600 font-medium").props(
            f'title="{config["tooltip"]}"'
        )

    def _render_compact_department_path(self, department_path: str):
        """Renders a compact display of the department path with adaptability.
        
        This function takes a department path string and processes it to create a
        breadcrumb-style display. It cleans and splits the path based on specific
        delimiters, then determines how to present the path based on its length.  If
        the path is short, it displays all parts; if long, it shows the first  and last
        parts with ellipses in between for clarity.
        
        Args:
            department_path: The path of the department as a string.
        """
        if not department_path:
            return

        # Clean and split department path
        path_parts = []
        if " → " in department_path:
            path_parts = [p.strip() for p in department_path.split(" → ") if p.strip()]
        elif "/" in department_path:
            path_parts = [p.strip() for p in department_path.split("/") if p.strip()]
        else:
            path_parts = [department_path.strip()]

        # Create breadcrumb-style display
        with ui.row().classes("items-center gap-1 flex-wrap"):
            ui.icon("folder", size="0.9rem").classes("text-gray-400")

            if len(path_parts) <= 2:
                # Short path - show all
                ui.label(" / ".join(path_parts)).classes(
                    "text-sm text-gray-600 truncate"
                ).style("max-width: 300px")
            else:
                # Long path - show first ... last
                ui.label(f"{path_parts[0]} / ... / {path_parts[-1]}").classes(
                    "text-sm text-gray-600 truncate"
                ).style("max-width: 300px").props(f'title="{" → ".join(path_parts)}"')

    def _render_profile_download_menu(self, profile_id: str):
        """Render a compact profile download menu."""
        with ui.dropdown_button("Скачать", icon="file_download").props(
            "outlined color=blue-grey size=sm"
        ).classes("min-w-[100px]"):

            ui.item(
                "JSON данные",
                on_click=lambda: self._request_download(profile_id, "json"),
            ).props("clickable")

            ui.item(
                "Word документ",
                on_click=lambda: self._request_download(profile_id, "docx"),
            ).props("clickable")

            ui.item(
                "Markdown",
                on_click=lambda: self._request_download(profile_id, "markdown"),
            ).props("clickable")

    def _render_detailed_profile_view(self):
        """Render a detailed profile view with a tabbed interface."""
        profile = self.current_profile
        if not profile:
            return

        with ui.card().classes("w-full"):
            # Заголовок профиля с версией
            self._render_enhanced_header(profile)

            # Табированный интерфейс
            self._render_tab_interface()

    def _render_enhanced_header(self, profile: Dict[str, Any]):
        """
        @doc
        Рендеринг расширенного заголовка профиля с статусом и версией.

        Args:
            profile: Данные профиля

        Examples:
          python> viewer._render_enhanced_header(profile_data)
          python> # Отрендерен заголовок со статусом
        """
        with ui.card_section().classes("bg-primary text-white"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column():
                    # Заголовок с статус badge
                    with ui.row().classes("items-center gap-3"):
                        title = profile.get("position_title", "Профиль должности")
                        ui.label(title).classes("text-h5 font-bold")
                        self._render_status_badge(profile)

                    # Путь департамента с красивым форматированием
                    with ui.column().classes("gap-1 mt-2"):
                        ui.label("Организационная структура:").classes(
                            "text-body2 text-grey-7 text-weight-medium"
                        )
                        self._render_hierarchy_path(profile.get("department_path", ""))

                    # Информация о версии и дате
                    with ui.row().classes("items-center gap-4 mt-2"):
                        version = profile.get("version", "1.0")
                        ui.label(f"📄 Версия {version}").classes(
                            "text-caption opacity-80"
                        )

                        created_at = profile.get("created_at")
                        if created_at:
                            formatted_date = self._format_datetime(created_at)
                            ui.label(f"📅 {formatted_date}").classes(
                                "text-caption opacity-80"
                            )

                        author = profile.get("created_by_username")
                        if author:
                            ui.label(f"👤 {author}").classes("text-caption opacity-80")

                # Кнопки действий
                with ui.row().classes("gap-2"):
                    # Навигация между версиями (если доступно)
                    if len(self.profiles_list) > 1:
                        ui.button(
                            icon="chevron_left", on_click=self._previous_version
                        ).props("flat round dense text-color=white").tooltip(
                            "Предыдущая версия"
                        )

                        ui.button(
                            icon="chevron_right", on_click=self._next_version
                        ).props("flat round dense text-color=white").tooltip(
                            "Следующая версия"
                        )

                        ui.button(icon="list", on_click=self._show_versions_list).props(
                            "flat round dense text-color=white"
                        ).tooltip("Все версии")

                    ui.button(icon="close", on_click=self._close_detailed_view).props(
                        "flat round text-color=white"
                    )

    def _render_status_badge(self, profile: Dict[str, Any]):
        """Render a status badge for the profile."""
        status = profile.get("status", "unknown")
        status_config = {
            "completed": {"icon": "🟢", "color": "positive", "text": "Готов"},
            "draft": {"icon": "🟡", "color": "warning", "text": "Черновик"},
            "in_progress": {"icon": "⚙️", "color": "info", "text": "В работе"},
            "archived": {"icon": "📦", "color": "grey", "text": "Архив"},
        }

        config = status_config.get(
            status, {"icon": "❓", "color": "grey", "text": "Неизвестно"}
        )
        ui.chip(f"{config['icon']} {config['text']}", color=config["color"]).classes(
            "text-white"
        )

    def _render_tab_interface(self):
        """Renders a tabbed interface with progressive disclosure."""
        with ui.tabs().classes("w-full") as tabs:
            content_tab = ui.tab("content", label="📄 Содержание", icon="visibility")

            # Advanced tabs shown only when there's content or multiple versions
            if len(self.profiles_list) > 1:
                versions_tab = ui.tab("versions", label="🔄 Версии", icon="history")
            else:
                versions_tab = None

            # Progressive disclosure for advanced features
            with ui.expansion("⚙️ Дополнительные возможности", icon="settings").classes(
                "w-full mt-2"
            ):
                with ui.column().classes("gap-2"):
                    ui.label("Расширенные опции просмотра профиля").classes(
                        "text-body2 text-grey-6 mb-2"
                    )

                    with ui.row().classes("gap-2 flex-wrap"):
                        metadata_tab = ui.tab(
                            "metadata", label="⚙️ Метаданные", icon="info"
                        ).classes("min-w-fit")
                        markdown_tab = ui.tab(
                            "markdown", label="📝 Markdown", icon="article"
                        ).classes("min-w-fit")

                        # Additional advanced features
                        ui.button(
                            "🔍 Анализ профиля",
                            icon="analytics",
                            on_click=self._show_profile_analysis,
                        ).props("outlined dense")
                        ui.button(
                            "📊 Сравнить версии",
                            icon="compare",
                            on_click=self._compare_versions,
                        ).props("outlined dense").set_enabled(
                            len(self.profiles_list) > 1
                        )

        with ui.tab_panels(tabs, value=content_tab).classes("w-full"):
            # Таб содержания профиля (основной контент)
            with ui.tab_panel(content_tab):
                with ui.scroll_area().classes("max-h-[60vh]"):
                    self._render_profile_content_section(
                        self.current_profile.get("json_data", {})
                    )

            # Условные табы для progressive disclosure
            if versions_tab:
                with ui.tab_panel(versions_tab):
                    with ui.scroll_area().classes("max-h-[60vh]"):
                        self._render_versions_management()

            # Advanced tabs (only if expansion is opened)
            try:
                with ui.tab_panel(metadata_tab):
                    with ui.scroll_area().classes("max-h-[60vh]"):
                        self._render_profile_metadata(self.current_profile)

                with ui.tab_panel(markdown_tab):
                    with ui.scroll_area().classes("max-h-[60vh]"):
                        self._render_markdown_view()
            except Exception as e:
                # Tab panels may not exist if not created yet
                logger.debug("Optional tab panels not rendered", exc_info=e)

        # Действия в футере
        self._render_profile_actions()

    def _render_versions_management(self):
        """Render version management for the profile.
        
        This function displays the version management interface for the current
        profile.  It checks the number of profiles in `self.profiles_list` to determine
        whether to  show details for a single version or a list of multiple versions.
        For a single  version, it presents the current version's details, including
        version number,  creation date, and author. For multiple versions, it lists all
        versions with  options to view or download each version, highlighting the
        current version.
        """
        with ui.column().classes("w-full gap-4 p-4"):
            ui.label("🔄 Управление версиями").classes("text-h6 font-medium")

            if len(self.profiles_list) <= 1:
                # Одна версия или нет данных о версиях
                with ui.card().classes("w-full"):
                    with ui.card_section():
                        ui.label("📄 Текущая версия").classes(
                            "text-subtitle1 font-medium"
                        )
                        version = self.current_profile.get("version", "1.0")
                        created_at = self.current_profile.get("created_at")
                        author = self.current_profile.get(
                            "created_by_username", "unknown"
                        )

                        ui.label(f"Версия: {version}").classes("text-body1")
                        if created_at:
                            formatted_date = self._format_datetime(created_at)
                            ui.label(f"Создано: {formatted_date}").classes("text-body1")
                        ui.label(f"Автор: {author}").classes("text-body1")

                        ui.label("Это единственная версия профиля").classes(
                            "text-caption text-grey-6 mt-2"
                        )
            else:
                # Множественные версии
                ui.label(f"Всего версий: {len(self.profiles_list)}").classes(
                    "text-body1 mb-3"
                )

                # Список версий
                for i, profile in enumerate(self.profiles_list):
                    is_current = profile.get("profile_id") == self.current_profile.get(
                        "profile_id"
                    )

                    with ui.card().classes(
                        f"w-full {'border-2 border-primary' if is_current else ''}"
                    ):
                        with ui.card_section():
                            with ui.row().classes(
                                "w-full justify-between items-center"
                            ):
                                with ui.column():
                                    version_label = (
                                        f"📄 Версия {profile.get('version', f'1.{i}')}"
                                    )
                                    if is_current:
                                        version_label += " (текущая)"
                                    ui.label(version_label).classes(
                                        f"text-subtitle1 font-medium {'text-primary' if is_current else ''}"
                                    )

                                    created_at = profile.get("created_at")
                                    if created_at:
                                        formatted_date = self._format_datetime(
                                            created_at
                                        )
                                        ui.label(f"📅 {formatted_date}").classes(
                                            "text-body2"
                                        )

                                    author = profile.get(
                                        "created_by_username", "unknown"
                                    )
                                    ui.label(f"👤 {author}").classes("text-body2")

                                    # Статус версии
                                    status = profile.get("status", "unknown")
                                    status_text = {
                                        "completed": "Готова",
                                        "draft": "Черновик",
                                        "in_progress": "В работе",
                                    }.get(status, status)
                                    ui.label(f"📊 {status_text}").classes(
                                        "text-caption text-grey-6"
                                    )

                                with ui.column().classes("gap-2"):
                                    if not is_current:
                                        ui.button(
                                            "Просмотр",
                                            icon="preview",
                                            on_click=lambda p=profile: self._switch_to_version(
                                                p
                                            ),
                                        ).props("color=primary outlined dense")

                                    ui.button(
                                        "Скачать",
                                        icon="file_download",
                                        on_click=lambda p=profile: self._download_version(
                                            p
                                        ),
                                    ).props("color=blue outlined dense")

    def _render_markdown_view(self):
        """Renders the Markdown view of the profile."""
        with ui.column().classes("w-full gap-4 p-4"):
            # Заголовок с действиями
            with ui.row().classes("w-full justify-between items-center mb-4"):
                ui.label("📝 Markdown просмотр").classes("text-h6 font-medium")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Копировать", icon="content_copy", on_click=self._copy_markdown
                    ).props("color=blue outlined dense")

                    ui.button(
                        "Скачать MD",
                        icon="file_download",
                        on_click=lambda: self._request_download(
                            self.current_profile.get("profile_id"), "markdown"
                        ),
                    ).props("color=green outlined dense")

            # Markdown контент
            try:
                markdown_content = self._get_markdown_content()
                if markdown_content:
                    # Используем ui.markdown для отображения
                    ui.markdown(markdown_content).classes(
                        "prose prose-sm max-w-none p-4 bg-white rounded border"
                    )
                else:
                    with ui.card().classes("w-full bg-grey-50"):
                        with ui.card_section():
                            ui.label("📝 Генерация Markdown...").classes("text-body1")
                            ui.label(
                                "Markdown версия будет сгенерирована из JSON данных профиля"
                            ).classes("text-caption text-grey-6")

            except Exception as e:
                with ui.card().classes("w-full bg-red-50 border border-red-200"):
                    with ui.card_section():
                        ui.label("❌ Ошибка загрузки Markdown").classes(
                            "text-body1 text-red-700"
                        )
                        ui.label(f"Детали: {str(e)}").classes(
                            "text-caption text-red-600"
                        )

    def _render_profile_actions(self):
        """Render profile actions with a centralized download center."""
        with ui.card_actions():
            with ui.column().classes("w-full gap-4"):
                # Центр скачивания
                self._render_download_center()

                # Навигационные действия
                with ui.row().classes("w-full justify-between"):
                    with ui.row().classes("gap-2"):
                        if len(self.profiles_list) > 1:
                            ui.button(
                                "Все версии",
                                icon="history",
                                on_click=self._show_all_versions,
                            ).props("outlined color=primary")

                    ui.button(
                        "Закрыть", icon="close", on_click=self._close_detailed_view
                    ).props("outlined")

    def _render_download_center(self):
        """Render the centralized file download center for the profile."""
        with ui.card().classes("w-full bg-blue-50 border-l-4 border-blue-500"):
            with ui.card_section():
                with ui.row().classes("w-full items-center gap-3 mb-3"):
                    ui.icon("file_download", size="1.5rem").classes("text-blue-600")
                    ui.label("📥 Скачать профиль").classes(
                        "text-h6 font-bold text-blue-900"
                    )

                ui.label(
                    "Выберите подходящий формат для скачивания профиля должности"
                ).classes("text-body2 text-blue-700 mb-4")

                # Опции скачивания с описаниями
                with ui.column().classes("w-full gap-3"):
                    # JSON опция
                    with ui.card().classes("w-full hover:shadow-md transition-shadow"):
                        with ui.card_section():
                            with ui.row().classes(
                                "w-full items-center justify-between"
                            ):
                                with ui.row().classes("items-center gap-3"):
                                    ui.icon("data_object", size="1.2rem").classes(
                                        "text-blue-600"
                                    )
                                    with ui.column().classes("gap-1"):
                                        ui.label("JSON данные").classes(
                                            "text-subtitle2 font-medium"
                                        )
                                        ui.label(
                                            "Структурированные данные для интеграции"
                                        ).classes("text-caption text-grey-6")

                                ui.button(
                                    "Скачать JSON",
                                    icon="download",
                                    on_click=lambda: self._request_download(
                                        self.current_profile.get("profile_id"), "json"
                                    ),
                                ).props("color=blue dense").tooltip(
                                    "Загрузить структурированные данные профиля в формате JSON для системной интеграции"
                                )

                    # Markdown опция
                    with ui.card().classes("w-full hover:shadow-md transition-shadow"):
                        with ui.card_section():
                            with ui.row().classes(
                                "w-full items-center justify-between"
                            ):
                                with ui.row().classes("items-center gap-3"):
                                    ui.icon("article", size="1.2rem").classes(
                                        "text-green-600"
                                    )
                                    with ui.column().classes("gap-1"):
                                        ui.label("Markdown документ").classes(
                                            "text-subtitle2 font-medium"
                                        )
                                        ui.label(
                                            "Читаемый формат для документации"
                                        ).classes("text-caption text-grey-6")

                                with ui.row().classes("gap-2"):
                                    ui.button(
                                        "Копировать",
                                        icon="content_copy",
                                        on_click=self._copy_markdown,
                                    ).props("outlined color=green dense").tooltip(
                                        "Скопировать Markdown-текст в буфер обмена для вставки в другие приложения"
                                    )

                                    ui.button(
                                        "Скачать MD",
                                        icon="download",
                                        on_click=lambda: self._request_download(
                                            self.current_profile.get("profile_id"),
                                            "markdown",
                                        ),
                                    ).props("color=green dense").tooltip(
                                        "Загрузить читаемый Markdown-файл для документации и публикации"
                                    )

                    # DOCX опция
                    with ui.card().classes("w-full hover:shadow-md transition-shadow"):
                        with ui.card_section():
                            with ui.row().classes(
                                "w-full items-center justify-between"
                            ):
                                with ui.row().classes("items-center gap-3"):
                                    ui.icon("description", size="1.2rem").classes(
                                        "text-purple-600"
                                    )
                                    with ui.column().classes("gap-1"):
                                        ui.label("Word документ").classes(
                                            "text-subtitle2 font-medium"
                                        )
                                        ui.label(
                                            "Готовый к печати и редактированию"
                                        ).classes("text-caption text-grey-6")

                                ui.button(
                                    "Скачать DOCX",
                                    icon="download",
                                    on_click=lambda: self._request_download(
                                        self.current_profile.get("profile_id"), "docx"
                                    ),
                                ).props("color=purple dense").tooltip(
                                    "Загрузить готовый к печати Word-документ с полным форматированием"
                                )

    # Методы для обработки действий

    def _switch_to_version(self, profile: Dict[str, Any]):
        """Switch to a different profile version."""
        self.current_profile = profile
        self._render_profile_content.refresh()
        ui.notify(
            f"Переключено на версию {profile.get('version', 'неизвестная')}",
            type="info",
        )

    def _download_version(self, profile: Dict[str, Any]):
        """Скачивание конкретной версии профиля"""
        profile_id = profile.get("profile_id")
        if profile_id and self.on_download_request:
            self.on_download_request(profile_id, "json")
        else:
            ui.notify("Невозможно скачать: нет ID профиля", type="negative")

    def _copy_markdown(self):
        """Copies Markdown content to the clipboard."""
        try:
            markdown_content = self._get_markdown_content()
            if markdown_content:
                # Безопасное копирование в буфер обмена
                import json

                escaped_content = json.dumps(markdown_content)
                # NiceGUI способ копирования в буфер
                ui.run_javascript(
                    f"""
                    navigator.clipboard.writeText({escaped_content}).then(() => {{
                        console.log("Markdown copied to clipboard");
                    }}).catch(err => {{
                        console.error("Failed to copy: ", err);
                    }});
                """
                )
                ui.notify("Markdown скопирован в буфер обмена", type="positive")
            else:
                ui.notify("Нет содержимого для копирования", type="warning")
        except Exception as e:
            ui.notify(f"Ошибка копирования: {str(e)}", type="negative")

    def _get_markdown_content(self) -> str:
        # Пока возвращаем заглушку - будет реализовано позже
        """Retrieve Markdown content for the current profile."""
        profile_id = self.current_profile.get("profile_id")

        # Проверяем кеш
        if profile_id in self.markdown_cache:
            return self.markdown_cache[profile_id]

        # Генерируем из JSON данных
        json_data = self.current_profile.get("json_data", {})
        if json_data:
            markdown = self._generate_markdown_from_json(json_data)
            self.markdown_cache[profile_id] = markdown
            return markdown

        return ""

    def _generate_markdown_from_json(self, json_data: Dict[str, Any]) -> str:
        """Generate Markdown from JSON profile data.
        
        This function constructs a Markdown representation of a job profile based on
        the provided JSON data. It extracts various sections such as position title,
        job summary, responsibility areas, responsibilities, professional skills, KPIs,
        qualification requirements, required education, and required experience. Each
        section is formatted appropriately, and the function handles different data
        types and structures within the JSON input.
        
        Args:
            json_data (Dict[str, Any]): A dictionary containing job profile information in JSON format.
        
        Returns:
            str: The generated Markdown string representing the job profile.
        """
        try:
            lines = []

            # Заголовок
            position_title = json_data.get("position_title", "Профиль должности")
            lines.append(f"# {position_title}")
            lines.append("")

            # Краткое описание
            if "job_summary" in json_data:
                lines.append("## 🎯 Краткое описание")
                lines.append(json_data["job_summary"])
                lines.append("")

            # Области ответственности
            if "responsibility_areas" in json_data:
                lines.append("## 📋 Области ответственности")
                for i, area in enumerate(json_data["responsibility_areas"][:3], 1):
                    if isinstance(area, dict):
                        area_names = area.get("area", [])
                        if area_names:
                            lines.append(f"### {i}. {area_names[0]}")
                            tasks = area.get("tasks", [])
                            for task in tasks[:5]:
                                lines.append(f"- {task}")
                            lines.append("")

            # Обязанности (Responsibilities) - отдельная секция
            if "responsibilities" in json_data:
                lines.append("## 🎯 Основные обязанности")
                responsibilities = json_data["responsibilities"]
                if isinstance(responsibilities, list):
                    for resp in responsibilities[:10]:
                        if isinstance(resp, str):
                            lines.append(f"- {resp}")
                        elif isinstance(resp, dict):
                            resp_text = resp.get(
                                "responsibility", resp.get("description", str(resp))
                            )
                            lines.append(f"- {resp_text}")
                elif isinstance(responsibilities, str):
                    lines.append(responsibilities)
                lines.append("")

            # Профессиональные навыки
            if "professional_skills" in json_data:
                lines.append("## 🛠️ Профессиональные навыки")
                for skill_group in json_data["professional_skills"][:3]:
                    if isinstance(skill_group, dict):
                        category = skill_group.get("skill_category", "Общие навыки")
                        lines.append(f"### {category}")
                        skills = skill_group.get("skills", [])
                        for skill in skills[:5]:
                            skill_name = (
                                skill
                                if isinstance(skill, str)
                                else skill.get("skill_name", str(skill))
                            )
                            lines.append(f"- {skill_name}")
                        lines.append("")

            # KPI
            if "kpi" in json_data:
                lines.append("## 📊 Ключевые показатели эффективности")
                kpi_data = json_data["kpi"]
                if isinstance(kpi_data, list):
                    for i, kpi in enumerate(kpi_data[:5], 1):
                        if isinstance(kpi, dict):
                            kpi_name = kpi.get("kpi_name", kpi.get("name", f"KPI {i}"))
                            lines.append(f"### {i}. {kpi_name}")

                            target = kpi.get("target_value", "")
                            if target:
                                lines.append(f"**Целевое значение:** {target}")

                            frequency = kpi.get("measurement_frequency", "")
                            if frequency:
                                lines.append(f"**Частота измерения:** {frequency}")

                            lines.append("")

            # Квалификационные требования
            if "qualification_requirements" in json_data:
                lines.append("## 🎓 Квалификационные требования")
                requirements = json_data["qualification_requirements"]
                if isinstance(requirements, list):
                    for req in requirements[:7]:
                        if isinstance(req, str):
                            lines.append(f"- {req}")
                        elif isinstance(req, dict):
                            req_text = req.get(
                                "requirement", req.get("description", str(req))
                            )
                            lines.append(f"- {req_text}")
                elif isinstance(requirements, str):
                    lines.append(requirements)
                lines.append("")

            # Требуемое образование
            if "required_education" in json_data:
                lines.append("## 📚 Требования к образованию")
                education = json_data["required_education"]
                if isinstance(education, list):
                    for edu in education[:5]:
                        lines.append(f"- {edu}")
                elif isinstance(education, str):
                    lines.append(education)
                lines.append("")

            # Требуемый опыт работы
            if "required_experience" in json_data:
                lines.append("## 💼 Требуемый опыт работы")
                experience = json_data["required_experience"]
                if isinstance(experience, str):
                    lines.append(experience)
                elif isinstance(experience, dict):
                    years = experience.get("years", "")
                    description = experience.get("description", "")
                    if years:
                        lines.append(f"**Стаж:** {years}")
                    if description:
                        lines.append(f"**Описание:** {description}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            return f"# Ошибка генерации Markdown\n\nНе удалось сгенерировать Markdown: {str(e)}"

    def _show_profile_analysis(self):
        """Notify that profile analysis will be available in future versions."""
        ui.notify("🔍 Анализ профиля будет доступен в следующих версиях", type="info")

    def _compare_versions(self):
        """
        @doc
        Сравнение различных версий профиля.

        Будущая функция для сравнения изменений между версиями профиля.

        Examples:
          python> viewer._compare_versions()
          python> # Показано сравнение версий
        """
        if len(self.profiles_list) <= 1:
            ui.notify("Нет версий для сравнения", type="warning")
        else:
            ui.notify(
                "📊 Сравнение версий будет доступно в следующих версиях", type="info"
            )

    def _show_all_versions(self):
        """Switch to the versions tab."""
        ui.notify("Переключение на таб управления версиями", type="info")

    def _previous_version(self):
        """Switch to the previous profile version.
        
        This method checks if there are multiple profiles in the profiles_list.  If so,
        it identifies the current profile's index and switches to the  previous profile
        version if the current index is greater than zero.  The switching is handled by
        the _switch_to_version method, which takes  the previous profile as an
        argument.
        """
        if len(self.profiles_list) > 1:
            current_index = next(
                (
                    i
                    for i, p in enumerate(self.profiles_list)
                    if p.get("profile_id") == self.current_profile.get("profile_id")
                ),
                0,
            )
            if current_index > 0:
                self._switch_to_version(self.profiles_list[current_index - 1])

    def _next_version(self):
        """Переключение на следующую версию"""
        if len(self.profiles_list) > 1:
            current_index = next(
                (
                    i
                    for i, p in enumerate(self.profiles_list)
                    if p.get("profile_id") == self.current_profile.get("profile_id")
                ),
                0,
            )
            if current_index < len(self.profiles_list) - 1:
                self._switch_to_version(self.profiles_list[current_index + 1])

    def _show_versions_list(self):
        """Display the versions list."""
        self.show_detailed_view = False
        self._render_profile_content.refresh()

    def _close_detailed_view(self):
        """Closes the detailed view of the profile."""
        self.show_detailed_view = False
        self.current_profile = None
        self._render_profile_content.refresh()

    def show_profile(self, profile_data: Dict[str, Any]):
        """def show_profile(self, profile_data: Dict[str, Any]):
        Display the profile synchronously.  This function loads and displays detailed
        information about a profile.  It first validates the provided profile_data and
        handles any errors  related to corrupted data. If the profile_data contains a
        task_result,  it extracts the profile information and updates the UI
        accordingly.  The function also manages the state for error recovery and
        refreshes  the profile content in the UI.
        
        Args:
            profile_data: Данные профиля от GeneratorComponent или API."""
        try:
            # Enhanced error detection and recovery
            if not self._validate_profile_data(profile_data):
                self._handle_corrupted_data_sync(
                    "Invalid profile data structure", profile_data
                )
                return

            # Если это результат генерации, извлекаем нужные данные
            if "task_result" in profile_data:
                result = profile_data["task_result"]
                if result and "profile" in result:
                    profile_id = result.get("profile_id")
                    if profile_id:
                        # Показываем уведомление о загрузке профиля
                        ui.notify(f"Загрузка профиля {profile_id}...", type="info")
                        adapted_data = self._adapt_generation_result(result)
                        self.current_profile = adapted_data
                    else:
                        # Показываем данные из результата генерации
                        adapted_data = self._adapt_generation_result(result)
                        self.current_profile = adapted_data
                else:
                    self._handle_corrupted_data_sync(
                        "Нет данных профиля в результате", profile_data
                    )
                    return
            else:
                # Это уже готовые данные профиля
                self.current_profile = profile_data

            # Save state for recovery
            if self.error_recovery_coordinator and not self.is_corrupted:
                self._save_component_state()

            # Обновляем состояние и UI
            self.show_detailed_view = True
            self.is_corrupted = False  # Reset corruption flag on successful load
            self._render_profile_content.refresh()

        except Exception as e:
            logger.error(f"Error showing profile: {e}")
            self._handle_profile_error_sync("display_error", str(e), profile_data)

    def _adapt_generation_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Adapts the generation result to a display format."""
        profile = result.get("profile", {})
        metadata = result.get("metadata", {})

        return {
            "profile_id": result.get("profile_id"),
            "position_title": profile.get(
                "position_title", result.get("position", "Неизвестная должность")
            ),
            "department_path": profile.get(
                "department", result.get("department", "Неизвестный департамент")
            ),
            "json_data": profile,
            "metadata": metadata,
            "generation_metadata": metadata,
            "created_at": result.get("created_at"),
            "created_by_username": result.get("created_by_username"),
            "version": result.get("version", "1.0"),
            "status": "completed",
        }

    def _render_profile_basic_info(self, profile_data: Dict[str, Any]):
        """Displays basic profile information."""
        with ui.expansion("📋 Основная информация", value=True).classes("w-full"):
            with ui.grid(columns="1fr 1fr").classes("gap-4 p-4"):
                # Левая колонка
                with ui.column().classes("gap-3"):
                    self._render_info_item(
                        "Должность", profile_data.get("position_title")
                    )
                    # Используем новый красивый метод для отображения иерархии
                    with ui.column().classes("gap-2"):
                        with ui.row().classes("items-center gap-3"):
                            ui.label("Департамент:").classes(
                                "text-weight-medium min-w-28 text-grey-7"
                            )
                        self._render_hierarchy_path(profile_data.get("department_path"))
                    self._render_info_item("Версия", profile_data.get("version"))
                    self._render_info_item("Статус", profile_data.get("status"))

                # Правая колонка
                with ui.column().classes("gap-3"):
                    created_at = profile_data.get("created_at")
                    self._render_info_item("Создан", self._format_datetime(created_at))
                    updated_at = profile_data.get("updated_at")
                    self._render_info_item(
                        "Обновлен", self._format_datetime(updated_at)
                    )
                    self._render_info_item(
                        "Автор", profile_data.get("created_by_username")
                    )
                    if profile_data.get("employee_name"):
                        self._render_info_item(
                            "Сотрудник", profile_data.get("employee_name")
                        )

    def _render_info_item(self, label: str, value: Any):
        """
        @doc
        Отображение элемента информации.

        Args:
            label: Название поля
            value: Значение поля

        Examples:
          python> viewer._render_info_item("Должность", "Java-разработчик")
          python> # Отрендерен элемент информации
        """
        with ui.row().classes("items-center gap-3"):
            ui.label(f"{label}:").classes("text-weight-medium min-w-28 text-grey-7")
            ui.label(str(value or "Не указано")).classes("text-body1")

    def _render_hierarchy_path(self, department_path: str):
        """
        @doc
        Красивое отображение длинного иерархического пути.

        Args:
            department_path: Строка с путем через разделители (/ или →)

        Examples:
          python> viewer._render_hierarchy_path("Блок → Департамент → Отдел → Группа")
          python> # Отрендерен многоуровневый путь с иконками
        """
        if not department_path:
            ui.label("Не указано").classes("text-body1 text-grey-5")
            return

        # Разбиваем путь на компоненты
        path_parts = []
        if " → " in department_path:
            path_parts = [p.strip() for p in department_path.split(" → ") if p.strip()]
        elif "/" in department_path:
            path_parts = [p.strip() for p in department_path.split("/") if p.strip()]
        else:
            path_parts = [department_path.strip()]

        # Отображаем как многоуровневую структуру
        with ui.column().classes("gap-1"):
            # Для коротких путей (1-2 уровня) показываем в одну строку
            if len(path_parts) <= 2:
                ui.label(" → ".join(path_parts)).classes("text-body1")
            else:
                # Для длинных путей отображаем иерархично с отступами (поддержка до 6 уровней)
                for i, part in enumerate(path_parts):
                    indent = "  " * i  # Отступы для иерархии
                    if i == 0:
                        icon = "🏢"  # Уровень 1: Блок
                    elif i == 1:
                        icon = "🏬"  # Уровень 2: Департамент
                    elif i == 2:
                        icon = "📋"  # Уровень 3: Управление
                    elif i == 3:
                        icon = "📂"  # Уровень 4: Отдел
                    elif i == 4:
                        icon = "📁"  # Уровень 5: Под-отдел
                    elif i == 5:
                        icon = "👥"  # Уровень 6: Группа
                    else:
                        icon = "🔹"  # Дополнительные уровни (если есть)

                    with ui.row().classes("items-center gap-1"):
                        ui.label(indent).classes(
                            "text-mono text-transparent"
                        )  # Невидимые отступы
                        ui.label(icon).classes("text-sm")
                        ui.label(part).classes(
                            "text-body2"
                            if i < len(path_parts) - 1
                            else "text-body1 text-weight-medium"
                        )

    def _render_profile_content_section(self, json_data: Dict[str, Any]):
        """Render the content section of a profile.
        
        This function displays a structured overview of a profile, including a job
        summary, responsibility areas, professional skills, and key performance
        indicators (KPI). It processes the provided JSON data to extract and format
        these details, ensuring that only a limited number of items are shown for each
        category, with indications for any additional items.
        
        Args:
            json_data (Dict[str, Any]): JSON data containing profile information.
        """
        with ui.expansion("📄 Содержание профиля", value=False).classes("w-full"):
            with ui.column().classes("gap-4 p-4"):

                # Краткое описание
                if json_data.get("job_summary"):
                    ui.label("🎯 Краткое описание").classes("text-h6 font-medium")
                    ui.label(json_data["job_summary"]).classes("text-body1 mb-4")

                # Области ответственности
                if json_data.get("responsibility_areas"):
                    ui.label("📋 Области ответственности").classes(
                        "text-h6 font-medium mb-2"
                    )

                    areas = json_data["responsibility_areas"]
                    for i, area in enumerate(areas[:3], 1):
                        if isinstance(area, dict):
                            area_names = area.get("area", [])
                            if isinstance(area_names, list) and area_names:
                                ui.label(f"{i}. {area_names[0]}").classes(
                                    "text-body1 font-medium"
                                )

                            tasks = area.get("tasks", [])
                            if tasks:
                                with ui.column().classes("ml-4 gap-1"):
                                    for task in tasks[:3]:
                                        ui.label(f"• {task}").classes("text-body2")
                                    if len(tasks) > 3:
                                        remaining_tasks = len(tasks) - 3
                                        txt = f"... и еще {remaining_tasks}"
                                        ui.label(txt).classes(
                                            "text-caption text-grey-6"
                                        )

                # Профессиональные навыки
                if json_data.get("professional_skills"):
                    ui.label("🛠️ Профессиональные навыки").classes(
                        "text-h6 font-medium mb-2"
                    )

                    skills = json_data["professional_skills"]
                    for skill_group in skills[:2]:
                        if isinstance(skill_group, dict):
                            category = skill_group.get("skill_category", "Общие навыки")
                            ui.label(f"▸ {category}").classes("text-body1 font-medium")

                            skills_list = skill_group.get("skills", [])
                            if skills_list:
                                with ui.column().classes("ml-4 gap-1"):
                                    for skill in skills_list[:4]:
                                        if isinstance(skill, dict):
                                            skill_name = skill.get(
                                                "skill_name",
                                                skill.get("name", str(skill)),
                                            )
                                        else:
                                            skill_name = str(skill)
                                        ui.label(f"• {skill_name}").classes(
                                            "text-body2"
                                        )
                                    if len(skills_list) > 4:
                                        remaining = len(skills_list) - 4
                                        ui.label(
                                            f"... и еще {remaining} навыков"
                                        ).classes("text-caption text-grey-6")

                # KPI и цели
                if json_data.get("kpi"):
                    ui.label("📊 Ключевые показатели (KPI)").classes(
                        "text-h6 font-medium mb-2"
                    )

                    kpi_data = json_data["kpi"]
                    if isinstance(kpi_data, list):
                        for i, kpi in enumerate(kpi_data[:3], 1):
                            if isinstance(kpi, dict):
                                kpi_name = kpi.get(
                                    "kpi_name", kpi.get("name", f"KPI {i}")
                                )
                                ui.label(f"{i}. {kpi_name}").classes("text-body1")
                            else:
                                ui.label(f"{i}. {str(kpi)}").classes("text-body1")

    def _render_profile_metadata(self, profile_data: Dict[str, Any]):
        """Render profile metadata for generation information.
        
        This function extracts and displays metadata related to the generation process,
        including generation time, token usage, and model details. It organizes the
        information into a user interface layout, presenting performance metrics and
        technical details in a structured format.
        
        Args:
            profile_data (Dict[str, Any]): Profile data containing generation metadata.
        
        Returns:
            None: This function does not return a value.
        """
        metadata = profile_data.get("generation_metadata") or profile_data.get(
            "metadata"
        )
        if not metadata:
            return

        with ui.expansion("⚙️ Метаданные генерации").classes("w-full"):
            with ui.grid(columns="1fr 1fr").classes("gap-4 p-4"):
                # Производительность
                with ui.column().classes("gap-2"):
                    ui.label("📊 Производительность").classes("text-body1 font-medium")

                    time_taken = metadata.get(
                        "generation_time_seconds", metadata.get("time_taken", 0)
                    )
                    self._render_info_item("Время генерации", f"{time_taken:.1f} сек")

                    tokens = metadata.get("tokens_used", metadata.get("tokens", {}))
                    if isinstance(tokens, dict):
                        total_tokens = tokens.get("total", 0)
                        input_tokens = tokens.get("input", 0)
                        output_tokens = tokens.get("output", 0)
                        self._render_info_item("Всего токенов", f"{total_tokens:,}")
                        if input_tokens:
                            self._render_info_item("Входные", f"{input_tokens:,}")
                        if output_tokens:
                            self._render_info_item("Выходные", f"{output_tokens:,}")
                    elif isinstance(tokens, int):
                        self._render_info_item("Токены", f"{tokens:,}")

                # Технические детали
                with ui.column().classes("gap-2"):
                    ui.label("🔧 Технические детали").classes("text-body1 font-medium")
                    model = metadata.get("model_used", metadata.get("model", ""))
                    self._render_info_item("Модель", model)

                    if metadata.get("prompt_name"):
                        self._render_info_item("Промпт", metadata["prompt_name"])
                    if metadata.get("prompt_version"):
                        self._render_info_item(
                            "Версия промпта", metadata["prompt_version"]
                        )

                    if metadata.get("langfuse_trace_id"):
                        ui.label("🔍 Trace ID:").classes(
                            "text-weight-medium text-grey-7"
                        )
                        ui.label(metadata["langfuse_trace_id"]).classes(
                            "text-caption font-mono"
                        )

    def _format_datetime(self, datetime_str: str) -> str:
        """Format a date and time string in ISO format for display.
        
        Args:
            datetime_str: A string containing the date in ISO format.
        
        Returns:
            str: The formatted date.
        """
        if not datetime_str:
            return "Не указано"

        try:
            # Парсим ISO формат даты
            if "T" in datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(datetime_str)

            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.debug(f"Error formatting datetime {datetime_str}: {e}")
            return str(datetime_str)

    def _request_download(self, profile_id: str, format_type: str):
        """
        @doc
        Запрос скачивания профиля с обработкой ошибок.

        Вызывает событие для FilesManagerComponent с fallback обработкой.

        Args:
            profile_id: ID профиля для скачивания
            format_type: Тип файла ("json", "markdown", "docx")

        Examples:
          python> viewer._request_download("profile123", "json")
          python> # Отправлен запрос на скачивание JSON
        """
        try:
            if not profile_id:
                ui.notify("❌ Невозможно скачать: нет ID профиля", type="negative")
                return

            if not self.on_download_request:
                ui.notify("❌ Функция скачивания недоступна", type="negative")
                return

            # Показываем индикатор загрузки
            ui.notify(f"📥 Подготовка файла {format_type.upper()}...", type="info")

            # Вызываем метод скачивания
            self.on_download_request(profile_id, format_type)

        except Exception as e:
            logger.error(f"Error requesting download: {e}")
            ui.notify(f"❌ Ошибка подготовки скачивания: {str(e)}", type="negative")

    def show_profile_list(self, profiles_data):
        """Display a list of profiles with support for a new data structure.
        
        This function processes the provided profiles_data, which can be either  a list
        of profiles or a dictionary containing extended information.  It logs the type
        and content of profiles_data, and based on the  structure, it determines how to
        display the profiles. If the view mode  is set to "single", it immediately
        shows the first profile. Otherwise,  it prepares to display multiple profiles
        or a list view.
        
        Args:
            profiles_data: Can be a list of profiles or a dictionary with
                extended information.
        """
        logger.info(
            f"🔥 DEBUG: ProfileViewerComponent.show_profile_list called with profiles_data type: {type(profiles_data)}"
        )
        if isinstance(profiles_data, dict):
            logger.info(f"🔥 DEBUG: profiles_data keys: {list(profiles_data.keys())}")
            profiles = profiles_data.get("profiles", [])
            logger.info(f"🔥 DEBUG: Found {len(profiles)} profiles in data")
        else:
            logger.info(
                f"🔥 DEBUG: profiles_data length: {len(profiles_data) if hasattr(profiles_data, '__len__') else 'N/A'}"
            )
        # Обработка новой структуры данных от SearchComponent
        if isinstance(profiles_data, dict):
            self.profiles_list = profiles_data.get("profiles", [])
            status_info = profiles_data.get("status", {})
            view_mode = profiles_data.get("view_mode", "list")

            # Если это режим единственного профиля - сразу показываем его
            if view_mode == "single" and self.profiles_list:
                self.show_profile(self.profiles_list[0])
                return

            # Если несколько профилей или режим списка
            self.show_detailed_view = False
            self.current_profile = None
        else:
            # Старый формат - просто список
            self.profiles_list = profiles_data or []
            self.show_detailed_view = False
            self.current_profile = None

        self._render_profile_content.refresh()

    async def clear_display(self):
        """Clears the display of profiles and resets related states."""
        await self._cleanup_resources()

        self.profiles_list = []
        self.current_profile = None
        self.show_detailed_view = False
        self.is_corrupted = False
        self.recovery_mode = False

        # Clear caches
        self.markdown_cache.clear()
        self.temp_data_cache.clear()
        self.loading_states.clear()

        self._render_profile_content.refresh()

    # === Error Recovery and Resource Management Methods ===

    def _validate_profile_data(self, profile_data: Any) -> bool:
        """Validate the structure of profile data to detect corruption.
        
        This function checks if the provided profile_data is a dictionary and
        validates its structure based on the presence of the "task_result" key.  If
        "task_result" exists, it further verifies that it contains a valid  "profile"
        dictionary. If the structure does not meet the required  criteria, appropriate
        warnings are logged.
        """
        if not isinstance(profile_data, dict):
            logger.warning("Profile data is not a dictionary")
            return False

        # Check for minimum required structure
        if "task_result" in profile_data:
            result = profile_data.get("task_result")
            if not isinstance(result, dict):
                logger.warning("task_result is not a dictionary")
                return False

            # Validate generation result structure
            if "profile" not in result or not isinstance(result["profile"], dict):
                logger.warning("Invalid generation result structure")
                return False

        else:
            # Direct profile data - check for basic structure
            # Accept any dict as valid profile data for now
            if not isinstance(profile_data, dict):
                logger.warning("Profile data is not a dictionary")
                return False

        return True

    def _handle_corrupted_data_sync(self, error_message: str, corrupted_data: Any):
        """Handles the synchronization of corrupted data."""
        logger.warning(f"Profile data corruption detected: {error_message}")
        self.is_corrupted = True
        self.current_profile = None
        self._render_profile_content.refresh()

    async def _handle_corrupted_data(self, error_message: str, corrupted_data: Any):
        """Handle corrupted profile data and initiate recovery options.
        
        Args:
            error_message: Description of the corruption.
            corrupted_data: The corrupted data for analysis.
        """
        self.is_corrupted = True
        logger.error(f"Profile data corruption detected: {error_message}")

        # Report to error recovery coordinator
        if self.error_recovery_coordinator:
            try:
                error = Exception(f"data_corruption: {error_message}")
                recovered = (
                    await self.error_recovery_coordinator.handle_component_error(
                        "profile_viewer_component", error, attempt_recovery=True
                    )
                )

                if recovered:
                    logger.info("Profile viewer component recovery successful")
                    ui.notify("🔄 Просмотр профилей восстановлен", type="positive")
                    return
            except Exception as recovery_error:
                logger.error(
                    f"Profile viewer error recovery coordination failed: {recovery_error}"
                )

        # Show corruption dialog with recovery options
        await self._show_corruption_dialog(error_message, corrupted_data)

    def _handle_profile_error_sync(
        self, operation: str, error_message: str, context_data: Any = None
    ):
        """Handles profile errors synchronously."""
        logger.error(f"Profile viewer error in {operation}: {error_message}")
        # Простая обработка ошибки без UI notifications
        self.is_corrupted = True
        self.current_profile = None
        self._render_profile_content.refresh()

    async def _handle_profile_error(
        self, operation: str, error_message: str, context_data: Any = None
    ):
        """
        @doc
        Handle profile-related errors with recovery.

        Args:
            operation: Name of the failed operation
            error_message: Error message from the failure
            context_data: Additional context data

        Examples:
          python> await viewer._handle_profile_error("display_error", "Parse failed", data)
          python> # Error handled with recovery coordination
        """
        logger.error(f"Profile viewer error in {operation}: {error_message}")

        # Report to error recovery coordinator
        if self.error_recovery_coordinator:
            try:
                error = Exception(f"{operation}: {error_message}")
                recovered = (
                    await self.error_recovery_coordinator.handle_component_error(
                        "profile_viewer_component", error, attempt_recovery=True
                    )
                )

                if recovered:
                    logger.info(
                        f"Profile viewer recovery successful for operation: {operation}"
                    )
                    return
            except Exception as recovery_error:
                logger.error(
                    f"Profile viewer error recovery coordination failed: {recovery_error}"
                )

        # Show user-friendly error message
        self._show_error_notification(operation, error_message)

    def _show_error_notification(self, operation: str, error_message: str):
        """Show user-friendly error notification based on the operation."""
        error_messages = {
            "display_error": "Не удалось отобразить профиль",
            "data_corruption": "Данные профиля повреждены",
            "load_error": "Ошибка загрузки профиля",
            "download_error": "Не удалось подготовить скачивание",
        }

        user_message = error_messages.get(operation, "Произошла ошибка")
        ui.notify(f"❌ {user_message}", type="negative")

        # Offer reset option
        ui.notify(
            "💡 Попробуйте обновить страницу или выбрать другой профиль", type="info"
        )

    async def _show_corruption_dialog(self, error_message: str, corrupted_data: Any):
        """Show a dialog for handling corrupted data."""
        with ui.dialog() as dialog:
            with ui.card().classes("border-l-4 border-red-500 bg-red-50 min-w-[450px]"):
                with ui.card_section().classes("py-6"):
                    # Header
                    with ui.row().classes("items-center gap-3 mb-4"):
                        ui.icon("error", size="2rem").classes("text-red-600")
                        ui.label("🔧 Данные профиля повреждены").classes(
                            "text-lg font-bold text-red-800"
                        )

                    # Error description
                    ui.label(
                        "Обнаружены проблемы с данными профиля. Возможно, файл был поврежден при передаче или сохранении."
                    ).classes("text-body1 text-red-700 mb-4")

                    # Technical details (expandable)
                    with ui.expansion("🔧 Технические детали", icon="info").classes(
                        "w-full mb-4"
                    ):
                        ui.label(error_message).classes(
                            "text-caption font-mono bg-grey-100 p-2 rounded"
                        )

                        # Show data structure info
                        if isinstance(corrupted_data, dict):
                            data_info = f"Тип данных: dict, ключи: {list(corrupted_data.keys())}"
                        else:
                            data_info = f"Тип данных: {type(corrupted_data).__name__}"

                        ui.label(data_info).classes("text-caption text-grey-6 mt-2")

                    # Recovery actions
                    with ui.row().classes("gap-3"):
                        ui.button(
                            "Попробовать восстановить",
                            icon="healing",
                            on_click=lambda: self._attempt_data_recovery(
                                dialog, corrupted_data
                            ),
                        ).props("color=blue")

                        ui.button(
                            "Очистить и начать заново",
                            icon="refresh",
                            on_click=lambda: self._reset_viewer_state(dialog),
                        ).props("color=orange")

                        ui.button("Закрыть", on_click=dialog.close).props("outlined")

        dialog.open()

    async def _attempt_data_recovery(self, dialog, corrupted_data: Any):
        """
        @doc
        Attempt to recover corrupted profile data.

        Args:
            dialog: Dialog to close after recovery
            corrupted_data: Data to attempt recovery on

        Examples:
          python> await viewer._attempt_data_recovery(dialog, bad_data)
          python> # Recovery attempted on corrupted data
        """
        dialog.close()

        try:
            logger.info("Attempting profile data recovery...")

            # Try different recovery strategies
            recovered_data = None

            # Strategy 1: Extract nested profile data
            if isinstance(corrupted_data, dict):
                if "task_result" in corrupted_data:
                    task_result = corrupted_data["task_result"]
                    if isinstance(task_result, dict) and "profile" in task_result:
                        recovered_data = {
                            "position_title": task_result.get(
                                "position", "Восстановленный профиль"
                            ),
                            "json_data": task_result["profile"],
                            "metadata": task_result.get("metadata", {}),
                            "status": "recovered",
                        }

                # Strategy 2: Use raw data as profile
                elif "json_data" not in corrupted_data and len(corrupted_data) > 0:
                    recovered_data = {
                        "position_title": "Восстановленный профиль",
                        "json_data": corrupted_data,
                        "status": "recovered",
                    }

            if recovered_data:
                logger.info("Data recovery successful")
                self.current_profile = recovered_data
                self.show_detailed_view = True
                self.is_corrupted = False
                self.recovery_mode = True

                self._render_profile_content.refresh()

                ui.notify("✅ Данные частично восстановлены", type="positive")
                ui.notify(
                    "⚠️ Проверьте содержимое профиля на корректность", type="warning"
                )
            else:
                ui.notify("❌ Не удалось восстановить данные", type="negative")
                await self._reset_viewer_state(None)

        except Exception as e:
            logger.error(f"Data recovery failed: {e}")
            ui.notify(f"❌ Ошибка восстановления: {str(e)}", type="negative")

    async def _reset_viewer_state(self, dialog):
        """Reset the viewer to a clean state after an error.
        
        Args:
            dialog: Dialog to close (can be None)
        """
        if dialog:
            dialog.close()

        logger.info("Resetting profile viewer state")

        # Clean up resources
        await self._cleanup_resources()

        # Reset all state
        self.current_profile = None
        self.profiles_list = []
        self.show_detailed_view = False
        self.is_corrupted = False
        self.recovery_mode = False
        self.current_tab = "content"

        # Clear caches
        self.markdown_cache.clear()
        self.temp_data_cache.clear()
        self.loading_states.clear()

        # Refresh UI
        self._render_profile_content.refresh()

        ui.notify("🔄 Просмотр профилей сброшен", type="info")

    def _save_component_state(self):
        """
        @doc
        Save current component state for recovery.

        Captures current viewer state to enable rollback on errors.

        Examples:
          python> viewer._save_component_state()
          python> # Current state saved for recovery
        """
        if not self.error_recovery_coordinator or self.is_corrupted:
            return

        # Prepare state data with size limits for performance
        profiles_data = []
        if self.profiles_list:
            # Limit to first 10 profiles to avoid large state size
            profiles_data = [
                {
                    k: v for k, v in profile.items() if k not in ["json_data"]
                }  # Exclude large json_data
                for profile in self.profiles_list[:10]
            ]

        current_profile_data = None
        if self.current_profile:
            # Create lightweight version of current profile
            current_profile_data = {
                "profile_id": self.current_profile.get("profile_id"),
                "position_title": self.current_profile.get("position_title"),
                "status": self.current_profile.get("status"),
                "created_at": self.current_profile.get("created_at"),
                # Store json_data only if it's small enough
                "has_json_data": bool(self.current_profile.get("json_data")),
            }

            json_data = self.current_profile.get("json_data", {})
            if isinstance(json_data, dict) and len(str(json_data)) < 10000:  # < 10KB
                current_profile_data["json_data"] = json_data

        state_data = {
            "current_profile": current_profile_data,
            "profiles_list": profiles_data,
            "show_detailed_view": self.show_detailed_view,
            "current_tab": self.current_tab,
            "recovery_mode": self.recovery_mode,
            "timestamp": time.time(),
        }

        try:
            self.error_recovery_coordinator.state_manager.save_state(
                "profile_viewer_component", state_data, ttl_seconds=900  # 15 minute TTL
            )
            logger.debug("Profile viewer component state saved for recovery")
        except Exception as e:
            logger.error(f"Failed to save profile viewer component state: {e}")

    async def _on_recovery_callback(self, recovered_state: Dict[str, Any]):
        """Handle state recovery from the error recovery coordinator.
        
        Args:
            recovered_state (Dict[str, Any]): Previously saved state data.
        """
        try:
            logger.info("Recovering profile viewer component state...")

            # Clean up current resources first
            await self._cleanup_resources()

            # Restore state data
            self.show_detailed_view = recovered_state.get("show_detailed_view", False)
            self.current_tab = recovered_state.get("current_tab", "content")
            self.recovery_mode = True
            self.is_corrupted = False

            # Restore profiles list
            profiles_data = recovered_state.get("profiles_list", [])
            if profiles_data:
                self.profiles_list = profiles_data

            # Restore current profile
            current_profile_data = recovered_state.get("current_profile")
            if current_profile_data:
                self.current_profile = current_profile_data

            # Refresh UI
            self._render_profile_content.refresh()

            ui.notify("🔄 Просмотр профилей восстановлен после ошибки", type="positive")
            logger.info("Profile viewer component state recovery completed")

        except Exception as e:
            logger.error(f"Error during profile viewer state recovery: {e}")
            ui.notify("⚠️ Частичное восстановление просмотра профилей", type="warning")

    async def _cleanup_resources(self):
        """Clean up managed resources to prevent leaks.
        
        This function cleans up temporary files, cached data, and other resources
        managed by the profile viewer. It first checks for any resources that  require
        cleanup through the error_recovery_coordinator and gathers  asynchronous
        cleanup tasks. After executing these tasks, it clears  temporary caches and
        loading states to ensure no residual data remains.
        """
        logger.debug("Cleaning up profile viewer resources")

        try:
            # Clean up managed resources through coordinator
            if self.error_recovery_coordinator and self.managed_resources:
                cleanup_tasks = []
                for resource in list(self.managed_resources):
                    if hasattr(resource, "cleanup"):
                        cleanup_tasks.append(resource.cleanup())

                if cleanup_tasks:
                    await asyncio.gather(*cleanup_tasks, return_exceptions=True)

                self.managed_resources.clear()

            # Clear temporary caches
            self.temp_data_cache.clear()
            self.markdown_cache.clear()

            # Clear loading states
            self.loading_states.clear()

            logger.debug("Profile viewer resource cleanup completed")

        except Exception as e:
            logger.error(f"Error during resource cleanup: {e}")

    def track_resource(self, resource):
        """Track a resource for automatic cleanup."""
        if hasattr(resource, "cleanup"):
            self.managed_resources.add(resource)

            # Also register with coordinator if available
            if self.error_recovery_coordinator and isinstance(
                resource, ManagedResource
            ):
                self.error_recovery_coordinator.cleanup_manager.track_resource(resource)

            logger.debug(
                f"Tracking resource: {getattr(resource, 'resource_id', 'unknown')}"
            )
        else:
            logger.warning("Resource does not implement cleanup method")

    async def reset_component_state(self):
        """Reset the component to a clean state."""
        logger.info("Resetting profile viewer component state")

        # Clean up resources
        await self._cleanup_resources()

        # Reset all state
        self.current_profile = None
        self.profiles_list = []
        self.show_detailed_view = False
        self.is_corrupted = False
        self.recovery_mode = False
        self.current_tab = "content"

        # Clear all caches and temporary data
        self.markdown_cache.clear()
        self.temp_data_cache.clear()
        self.loading_states.clear()

        # Refresh UI
        self._render_profile_content.refresh()

        ui.notify("🔄 Просмотр профилей сброшен", type="info")
