"""
@doc Profile Management API endpoints

Реализует CRUD операции для управления сгенерированными профилями должностей.
Включает получение, поиск, фильтрацию, обновление и удаление профилей.

Examples:
    python>
    # GET /api/profiles - получить список профилей с пагинацией
    # GET /api/profiles/{profile_id} - получить конкретный профиль
    # DELETE /api/profiles/{profile_id} - удалить профиль
    # PUT /api/profiles/{profile_id} - обновить метаданные профиля
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from typing import Optional
import json
import sqlite3
from datetime import datetime

import anyio

from ..models.schemas import ProfileListResponse, ProfileUpdateRequest
from .auth import get_current_user
from ..models.database import get_db_manager
from ..core.config import config
from ..utils.validators import (
    validate_profile_id,
    validate_pagination,
    validate_search_query,
    validate_optional_string,
    validate_status,
    validate_profile_update_request,
)
from ..utils.exceptions import (
    NotFoundError,
    ValidationError,
    DatabaseError,
    ServiceUnavailableError,
)
from ..core.storage_service import ProfileStorageService

router = APIRouter(prefix="/api/profiles", tags=["Profile Management"])
storage_service = ProfileStorageService()


@router.get("/", response_model=ProfileListResponse)
async def get_profiles(
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество записей на страницу"),
    department: Optional[str] = Query(None, description="Фильтр по департаменту"),
    position: Optional[str] = Query(None, description="Фильтр по должности"),
    search: Optional[str] = Query(
        None, description="Поиск по имени/департаменту/должности"
    ),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    current_user: dict = Depends(get_current_user),
):
    """
    @doc Получить список профилей с пагинацией и фильтрацией

    Возвращает список всех профилей с поддержкой пагинации, фильтрации по
    департаменту, должности, статусу и текстового поиска по всем полям.

    **Query Parameters:**
    - `page` (int): Номер страницы (по умолчанию: 1)
    - `limit` (int): Количество записей на страницу (1-100, по умолчанию: 20)
    - `department` (str, optional): Фильтр по названию департамента
      (поддерживает частичное совпадение)
    - `position` (str, optional): Фильтр по названию должности
      (поддерживает частичное совпадение)
    - `search` (str, optional): Текстовый поиск по имени сотрудника,
      департаменту и должности
    - `status` (str, optional): Фильтр по статусу
      ('completed', 'archived', 'in_progress')

    **Response Model:** ProfileListResponse
    - `profiles`: Массив профилей с базовой информацией
    - `pagination`: Метаданные пагинации (общее количество, страницы, навигация)
    - `filters_applied`: Примененные фильтры

    **Authentication:** Требуется Bearer Token

    Examples:
        bash>
        # 1. Получить первую страницу (5 записей на страницу)
        curl -X GET "http://localhost:8001/api/profiles/?page=1&limit=5" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json"

        # Response (200 OK):
        {
          "profiles": [
            {
              "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
              "department": "Группа анализа данных",
              "position": "Старший аналитик данных",
              "employee_name": "Иванова Анна Сергеевна",
              "status": "completed",
              "validation_score": 0.95,
              "completeness_score": 0.87,
              "created_at": "2025-01-10T14:30:22",
              "created_by_username": "admin",
              "actions": {
                "download_json": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/json",
                "download_md": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/md",
                "download_docx": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/docx"
              }
            }
          ],
          "pagination": {
            "page": 1,
            "limit": 5,
            "total": 8,
            "total_pages": 2,
            "has_next": true,
            "has_prev": false
          },
          "filters_applied": {
            "department": null,
            "position": null,
            "search": null,
            "status": null
          }
        }

        # 2. Фильтрация по департаменту (URL encoded)
        curl -X GET "http://localhost:8001/api/profiles/?department=%D0%93%D1%80%D1%83%D0%BF%D0%BF%D0%B0%20%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D0%B7%D0%B0%20%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Note: "Группа анализа данных" должно быть URL encoded

        # Response (200 OK) - только профили из указанного департамента:
        {
          "profiles": [
            {
              "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
              "department": "Группа анализа данных",
              "position": "Старший аналитик данных",
              "employee_name": "Иванова Анна Сергеевна",
              "status": "completed"
            }
          ],
          "pagination": {
            "page": 1,
            "limit": 20,
            "total": 1,
            "total_pages": 1,
            "has_next": false,
            "has_prev": false
          },
          "filters_applied": {
            "department": "Группа анализа данных",
            "position": null,
            "search": null,
            "status": null
          }
        }

        # 3. Текстовый поиск (поиск "analyst")
        curl -X GET "http://localhost:8001/api/profiles/?search=analyst" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (200 OK) - профили, содержащие "analyst" в названии должности:
        {
          "profiles": [
            {
              "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
              "department": "Группа анализа данных",
              "position": "Старший аналитик данных",
              "employee_name": "Иванова Анна Сергеевна"
            }
          ],
          "filters_applied": {
            "search": "analyst"
          }
        }

        # 4. Комбинированный поиск с пагинацией
        curl -X GET "http://localhost:8001/api/profiles/?page=2&limit=3&status=completed" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"
    """
    # Валидация параметров запроса
    page, limit = validate_pagination(page, limit)
    department = validate_optional_string(department, "department", max_length=200)
    position = validate_optional_string(position, "position", max_length=200)
    search = validate_search_query(search)
    if status:
        status = validate_status(status)

    def _fetch_profiles_sync() -> dict:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            # Базовый запрос
            base_query = """
                SELECT p.id as profile_id, p.department, p.position, p.employee_name,
                       p.created_at, p.updated_at, p.status, p.validation_score,
                       p.completeness_score, u.full_name as created_by_name, u.username as created_by_username
                FROM profiles p
                LEFT JOIN users u ON p.created_by = u.id
                WHERE 1=1
            """

            # Параметры для запроса
            params = []
            conditions = []

            # Применяем фильтры
            if department:
                conditions.append("p.department LIKE ?")
                params.append(f"%{department}%")

            if position:
                conditions.append("p.position LIKE ?")
                params.append(f"%{position}%")

            if search:
                conditions.append(
                    """
                    (p.employee_name LIKE ? OR
                     p.department LIKE ? OR
                     p.position LIKE ?)
                """
                )
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param])

            if status:
                conditions.append("p.status = ?")
                params.append(status)

            # Собираем финальный запрос с условиями
            where_clause = " AND " + " AND ".join(conditions) if conditions else ""
            count_query = f"SELECT COUNT(*) FROM profiles p WHERE 1=1{where_clause}"

            # Считаем общее количество
            cursor.execute(count_query, params)
            count_result = cursor.fetchone()
            total_count = count_result[0] if count_result else 0

            # Добавляем пагинацию
            offset = (page - 1) * limit
            final_query = f"""
                {base_query}{where_clause}
                ORDER BY p.created_at DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            # Выполняем основной запрос
            cursor.execute(final_query, params)
            rows = cursor.fetchall()

            profiles = []
            for row in rows:
                profile = {
                    "profile_id": row["profile_id"],
                    "department": row["department"],
                    "position": row["position"],
                    "employee_name": row["employee_name"],
                    "status": row["status"],
                    "validation_score": row["validation_score"],
                    "completeness_score": row["completeness_score"],
                    "created_at": row["created_at"],
                    "created_by_username": row["created_by_username"],
                    "actions": {
                        "download_json": f"/api/profiles/{row['profile_id']}/download/json",
                        "download_md": f"/api/profiles/{row['profile_id']}/download/md",
                        "download_docx": f"/api/profiles/{row['profile_id']}/download/docx",
                    },
                }
                profiles.append(profile)

            # Вычисляем метаданные пагинации
            total_pages = (total_count + limit - 1) // limit
            has_next = page < total_pages
            has_prev = page > 1

            return {
                "profiles": profiles,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_count,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_prev": has_prev,
                },
                "filters_applied": {
                    "department": department,
                    "position": position,
                    "search": search,
                    "status": status,
                },
            }

        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to fetch profiles: {str(e)}",
                operation="SELECT",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected database error: {str(e)}",
                operation="SELECT",
                table="profiles",
            )

    return await anyio.to_thread.run_sync(_fetch_profiles_sync)


@router.get("/{profile_id}")
async def get_profile(profile_id: str, current_user: dict = Depends(get_current_user)):
    """
    @doc Получить конкретный профиль по ID

    Возвращает полную информацию о профиле, включая все данные профиля,
    метаданные генерации и информацию о создателе.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля

    **Response:** Полный объект профиля с метаданными
    - `profile_id`: UUID профиля
    - `profile`: Полные данные профиля в JSON формате
    - `metadata`: Метаданные генерации (время, токены, модель)
    - `created_at`: Дата создания
    - `created_by_username`: Имя создателя
    - `actions`: Ссылки на действия (скачивание файлов)

    **Authentication:** Требуется Bearer Token

    Examples:
        bash>
        # 1. Получить профиль по ID
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json"

        # Response (200 OK):
        {
          "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
          "profile": {
            "position_info": {
              "title": "Старший аналитик данных",
              "department": "Группа анализа данных",
              "reporting_to": "Руководитель группы анализа данных",
              "subordinates": [],
              "employment_type": "full_time"
            },
            "responsibilities": [
              "Проведение глубокого анализа больших объемов данных",
              "Создание аналитических отчетов и дашбордов",
              "Разработка прогнозных моделей"
            ],
            "qualifications": {
              "education": "Высшее образование в области математики, статистики или IT",
              "experience": "От 3 лет опыта работы с данными",
              "skills": ["Python", "SQL", "Tableau", "Machine Learning"]
            },
            "kpis": [
              {
                "name": "Точность прогнозных моделей",
                "target_value": "> 85%",
                "measurement_frequency": "ежемесячно"
              }
            ]
          },
          "metadata": {
            "generation_id": "gen_20250110_143022_abc123",
            "model_used": "gemini-2.0-flash-exp",
            "tokens_used": 1250,
            "generation_time_ms": 3400,
            "langfuse_trace_id": "trace_abc123def456",
            "prompt_version": "v2.1"
          },
          "created_at": "2025-01-10T14:30:22",
          "created_by_username": "admin",
          "actions": {
            "download_json": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/json",
            "download_md": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/md",
            "download_docx": "/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/docx"
          }
        }

        # 2. Ошибка - профиль не найден
        curl -X GET "http://localhost:8001/api/profiles/nonexistent-profile-id" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-profile-id"
          }
        }

        # 3. Ошибка авторизации
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer invalid-token"

        # Response (401 Unauthorized):
        {
          "detail": "Invalid authentication token"
        }
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _get_profile_sync() -> dict:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT p.*, u.full_name as created_by_name
                FROM profiles p
                LEFT JOIN users u ON p.created_by = u.id
                WHERE p.id = ?
            """,
                (profile_id,),
            )

            row = cursor.fetchone()
            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            # Парсим JSON данные
            profile_data = json.loads(row["profile_data"])
            metadata = json.loads(row["metadata_json"])

            return {
                "profile_id": row["id"],
                "profile": profile_data.get("profile", profile_data),
                "metadata": metadata,
                "created_at": row["created_at"],
                "created_by_username": row["created_by_name"],
                "actions": {
                    "download_json": f"/api/profiles/{row['id']}/download/json",
                    "download_md": f"/api/profiles/{row['id']}/download/md",
                    "download_docx": f"/api/profiles/{row['id']}/download/docx",
                },
            }

        except json.JSONDecodeError as e:
            raise DatabaseError(
                f"Invalid JSON data in profile {profile_id}: {str(e)}",
                operation="JSON_DECODE",
                table="profiles",
            )
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to fetch profile {profile_id}: {str(e)}",
                operation="SELECT",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error fetching profile {profile_id}: {str(e)}",
                operation="SELECT",
                table="profiles",
            )

    return await anyio.to_thread.run_sync(_get_profile_sync)


@router.put("/{profile_id}")
async def update_profile_metadata(
    profile_id: str,
    update_request: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    @doc Обновить метаданные профиля (имя сотрудника, статус)

    Позволяет обновить метаданные существующего профиля. Поддерживается
    изменение имени сотрудника и статуса профиля.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля для обновления

    **Request Body:** ProfileUpdateRequest
    - `employee_name` (str, optional): Новое имя сотрудника (только кириллица, пробелы, дефисы)
    - `status` (str, optional): Новый статус ('completed', 'archived', 'in_progress')

    **Response:** Сообщение об успешном обновлении
    - `message`: Текст подтверждения
    - `profile_id`: UUID обновленного профиля

    **Authentication:** Требуется Bearer Token

    **Validation Rules:**
    - `employee_name`: Максимум 200 символов, только кириллица, пробелы, дефисы
    - `status`: Должен быть одним из допустимых значений

    Examples:
        bash>
        # 1. Успешное обновление имени и статуса
        curl -X PUT "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json" \
          -d '{
            "employee_name": "Петрова Мария Александровна",
            "status": "completed"
          }'

        # Response (200 OK):
        {
          "message": "Profile updated successfully",
          "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef"
        }

        # 2. Обновление только имени сотрудника
        curl -X PUT "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json" \
          -d '{
            "employee_name": "Сидоров Алексей Викторович"
          }'

        # Response (200 OK):
        {
          "message": "Profile updated successfully",
          "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef"
        }

        # 3. Ошибка валидации - неправильное имя с спецсимволами
        curl -X PUT "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json" \
          -d '{
            "employee_name": "John@Smith#123"
          }'

        # Response (422 Unprocessable Entity):
        {
          "detail": {
            "error": "Invalid employee_name format",
            "error_code": "VALIDATION_ERROR",
            "field": "employee_name",
            "details": {
              "allowed_pattern": "Only Cyrillic letters, spaces, and hyphens",
              "provided_value": "John@Smith#123"
            }
          }
        }

        # 4. Ошибка - профиль не найден
        curl -X PUT "http://localhost:8001/api/profiles/nonexistent-id" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json" \
          -d '{
            "employee_name": "Новое Имя"
          }'

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-id"
          }
        }

        # 5. Обновление статуса
        curl -X PUT "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json" \
          -d '{
            "status": "archived"
          }'
    """
    # Валидация profile_id и данных обновления
    profile_id = validate_profile_id(profile_id)
    validated_updates = validate_profile_update_request(
        employee_name=update_request.employee_name, status=update_request.status
    )

    def _update_sync() -> dict:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            # Проверяем существование профиля
            cursor.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,))
            if not cursor.fetchone():
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            # Подготавливаем поля для обновления из валидированных данных
            update_fields = []
            params = []

            for field_name, field_value in validated_updates.items():
                update_fields.append(f"{field_name} = ?")
                params.append(field_value)

            # Добавляем updated_at
            update_fields.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(profile_id)

            # Выполняем обновление
            update_query = f"""
                UPDATE profiles
                SET {', '.join(update_fields)}
                WHERE id = ?
            """

            cursor.execute(update_query, params)
            conn.commit()

            if cursor.rowcount == 0:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            return {"message": "Profile updated successfully", "profile_id": profile_id}

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to update profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error updating profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )

    return await anyio.to_thread.run_sync(_update_sync)


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str, current_user: dict = Depends(get_current_user)
):
    """
    @doc Удалить профиль (soft delete - помечаем как архивный)

    Выполняет «мягкое» удаление профиля, изменяя его статус на 'archived' вместо
    физического удаления из базы данных. Архивные профили можно восстановить.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля для архивирования

    **Response:** Подтверждение архивирования
    - `message`: Текст подтверждения операции
    - `profile_id`: UUID архивированного профиля
    - `status`: Новый статус профиля ('archived')

    **Authentication:** Требуется Bearer Token

    **Business Logic:**
    - Проверяет существование профиля
    - Проверяет, что профиль еще не архивирован
    - Изменяет статус на 'archived' с обновлением времени
    - Архивированные профили исключаются из обычных поисков

    Examples:
        bash>
        # 1. Успешное архивирование профиля
        curl -X DELETE "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json"

        # Response (200 OK):
        {
          "message": "Profile archived successfully",
          "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
          "status": "archived"
        }

        # 2. Ошибка - попытка архивировать уже архивированный профиль
        curl -X DELETE "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (422 Unprocessable Entity):
        {
          "detail": {
            "error": "Profile is already archived",
            "error_code": "VALIDATION_ERROR",
            "field": "status",
            "details": {
              "current_status": "archived",
              "operation": "delete"
            }
          }
        }

        # 3. Ошибка - профиль не найден
        curl -X DELETE "http://localhost:8001/api/profiles/nonexistent-profile-id" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-profile-id"
          }
        }

        # 4. Проверка результата архивирования через список профилей
        curl -X GET "http://localhost:8001/api/profiles/?status=archived" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N10.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response: список архивных профилей
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _delete_sync() -> dict:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            # Проверяем существование профиля
            cursor.execute(
                "SELECT id, status FROM profiles WHERE id = ?", (profile_id,)
            )
            row = cursor.fetchone()

            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            if row["status"] == "archived":
                raise ValidationError(
                    "Profile is already archived",
                    field="status",
                    details={"current_status": "archived", "operation": "delete"},
                )

            # Soft delete - помечаем как архивный
            cursor.execute(
                """
                UPDATE profiles
                SET status = 'archived', updated_at = ?
                WHERE id = ?
            """,
                (datetime.now().isoformat(), profile_id),
            )

            conn.commit()

            return {
                "message": "Profile archived successfully",
                "profile_id": profile_id,
                "status": "archived",
            }

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to delete profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error deleting profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )

    return await anyio.to_thread.run_sync(_delete_sync)


@router.post("/{profile_id}/restore")
async def restore_profile(
    profile_id: str, current_user: dict = Depends(get_current_user)
):
    """
    @doc Восстановить архивный профиль

    Восстанавливает архивированный профиль, возвращая ему статус 'completed'.
    Профиль снова становится доступным для обычных поисков и операций.

    **Path Parameters:**
    - `profile_id` (str): UUID архивированного профиля для восстановления

    **Response:** Подтверждение восстановления
    - `message`: Текст подтверждения операции
    - `profile_id`: UUID восстановленного профиля
    - `status`: Новый статус профиля ('completed')

    **Authentication:** Требуется Bearer Token

    **Business Logic:**
    - Проверяет существование профиля
    - Проверяет, что профиль действительно архивирован
    - Восстанавливает статус 'completed' с обновлением времени
    - Восстановленный профиль возвращается в обычные поиски

    Examples:
        bash>
        # 1. Успешное восстановление архивированного профиля
        curl -X POST "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/restore" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          -H "Content-Type: application/json"

        # Response (200 OK):
        {
          "message": "Profile restored successfully",
          "profile_id": "4aec3e73-c9bd-4d25-a123-456789abcdef",
          "status": "completed"
        }

        # 2. Ошибка - попытка восстановить неархивированный профиль
        curl -X POST "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/restore" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (422 Unprocessable Entity):
        {
          "detail": {
            "error": "Profile is not archived",
            "error_code": "VALIDATION_ERROR",
            "field": "status",
            "details": {
              "current_status": "completed",
              "operation": "restore"
            }
          }
        }

        # 3. Ошибка - профиль не найден
        curl -X POST "http://localhost:8001/api/profiles/nonexistent-profile-id/restore" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-profile-id"
          }
        }

        # 4. Проверка результата восстановления
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response: профиль со статусом 'completed'
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _restore_sync() -> dict:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            # Проверяем существование профиля
            cursor.execute(
                "SELECT id, status FROM profiles WHERE id = ?", (profile_id,)
            )
            row = cursor.fetchone()

            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            if row["status"] != "archived":
                raise ValidationError(
                    "Profile is not archived",
                    field="status",
                    details={"current_status": row["status"], "operation": "restore"},
                )

            # Восстанавливаем профиль
            cursor.execute(
                """
                UPDATE profiles
                SET status = 'completed', updated_at = ?
                WHERE id = ?
            """,
                (datetime.now().isoformat(), profile_id),
            )

            conn.commit()

            return {
                "message": "Profile restored successfully",
                "profile_id": profile_id,
                "status": "completed",
            }

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to restore profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error restoring profile {profile_id}: {str(e)}",
                operation="UPDATE",
                table="profiles",
            )

    return await anyio.to_thread.run_sync(_restore_sync)


@router.get("/{profile_id}/download/json")
async def download_profile_json(
    profile_id: str, current_user: dict = Depends(get_current_user)
):
    """
    @doc Скачать JSON файл профиля

    Скачивает полный профиль в JSON формате из файловой системы. Файл содержит
    как сами данные профиля, так и метаданные генерации.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля для скачивания

    **Response:** Файл JSON для скачивания
    - Content-Type: application/json
    - Content-Disposition: attachment
    - Имя файла: profile_{position}_{profile_id_short}.json

    **Authentication:** Требуется Bearer Token

    **File Location Logic:**
    - Файлы хранятся в /generated_profiles/{department}/
    - Путь вычисляется детерминистично по profile_id + created_at
    - Имя файла: {position}_{timestamp}.json

    **Error Cases:**
    - 404: Профиль не найден в базе данных
    - 404: JSON файл не найден в файловой системе
    - 401: Невалидный токен авторизации

    Examples:
        bash>
        # 1. Успешное скачивание JSON файла
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/json" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          --output "profile_data_analyst.json"

        # Response (200 OK): Скачивание файла начнется автоматически
        # Headers:
        # Content-Type: application/json
        # Content-Disposition: attachment; filename="profile_Старший_аналитик_данных_4aec3e73.json"
        # Content-Length: 15420

        # File content: Полные данные профиля в JSON формате

        # 2. Ошибка - файл не найден (профиль существует, но файлы удалены)
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/json" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile JSON file not found at /generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.json",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "file",
            "resource_id": "/generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.json"
          }
        }

        # 3. Ошибка - профиль не найден в базе данных
        curl -X GET "http://localhost:8001/api/profiles/nonexistent-profile-id/download/json" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-profile-id"
          }
        }

        # 4. Пример скачивания с корректным именем файла
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/json" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          --output "/tmp/my_profile_$(date +%Y%m%d).json" \
          --silent --show-error

        # Проверка результата скачивания:
        ls -la /tmp/my_profile_*.json
        file /tmp/my_profile_*.json  # Покажет 'JSON data'
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _get_json_download_info_sync() -> tuple[str, str]:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, department, position, created_at
                FROM profiles
                WHERE id = ?
            """,
                (profile_id,),
            )

            row = cursor.fetchone()
            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            created_at = datetime.fromisoformat(row["created_at"])
            json_path, _, _ = storage_service.get_profile_paths(
                profile_id=row["id"],
                department=row["department"],
                position=row["position"],
                created_at=created_at,
            )

            if not json_path.exists():
                raise NotFoundError(
                    f"Profile JSON file not found at {json_path}",
                    resource="file",
                    resource_id=str(json_path),
                )

            filename = f"profile_{row['position']}_{profile_id[:8]}.json"
            return str(json_path), filename

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to fetch profile {profile_id}: {str(e)}",
                operation="SELECT",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error downloading profile {profile_id}: {str(e)}",
                operation="FILE_ACCESS",
                table="profiles",
            )

    json_path_str, filename = await anyio.to_thread.run_sync(
        _get_json_download_info_sync
    )
    return FileResponse(
        path=json_path_str,
        filename=filename,
        media_type="application/json",
        headers={"Content-Disposition": "attachment"},
    )


@router.get("/{profile_id}/download/docx")
async def download_profile_docx(
    profile_id: str, current_user: dict = Depends(get_current_user)
):
    """
    @doc Скачать DOCX файл профиля

    Скачивает профиль в формате Microsoft Word (DOCX) из файловой системы.
    DOCX файл содержит профессионально отформатированный профиль готовый
    для редактирования и корпоративного документооборота.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля для скачивания

    **Response:** Файл Microsoft Word для скачивания
    - Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
    - Content-Disposition: attachment
    - Имя файла: profile_{position}_{profile_id_short}.docx

    **Authentication:** Требуется Bearer Token

    **File Location Logic:**
    - DOCX файлы хранятся рядом с JSON в /generated_profiles/{department}/
    - Путь вычисляется детерминистично по profile_id + created_at
    - Имя файла: {position}_{timestamp}.docx

    **DOCX Content Features:**
    - Корпоративные стили A101 (синий цвет, структурированные таблицы)
    - Профессиональные таблицы для навыков, KPI, инструментов
    - Заголовки с иконками и правильным форматированием
    - Метаданные генерации в подвале документа
    - Готовый для редактирования и печати формат

    **Error Cases:**
    - 404: Профиль не найден в базе данных
    - 404: DOCX файл не найден в файловой системе
    - 401: Невалидный токен авторизации

    Examples:
        bash>
        # 1. Успешное скачивание DOCX файла
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/docx" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
          --output "profile.docx"

        # Response (200 OK): Скачивание файла начнется автоматически
        # Headers:
        # Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
        # Content-Disposition: attachment; filename="profile_Старший_аналитик_данных_4aec3e73.docx"

        # 2. Ошибка - файл не найден (профиль существует, но DOCX файл удален)
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/docx" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile DOCX file not found at /generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.docx",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "file",
            "resource_id": "/generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.docx"
          }
        }
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _get_docx_download_info_sync() -> tuple[str, str]:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, department, position, created_at
                FROM profiles
                WHERE id = ?
            """,
                (profile_id,),
            )

            row = cursor.fetchone()
            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            created_at = datetime.fromisoformat(row["created_at"])
            _, _, docx_path = storage_service.get_profile_paths(
                profile_id=row["id"],
                department=row["department"],
                position=row["position"],
                created_at=created_at,
            )

            if not docx_path.exists():
                raise NotFoundError(
                    f"Profile DOCX file not found at {docx_path}",
                    resource="file",
                    resource_id=str(docx_path),
                )

            filename = f"profile_{row['position']}_{profile_id[:8]}.docx"
            return str(docx_path), filename

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to fetch profile {profile_id}: {str(e)}",
                operation="SELECT",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error downloading profile {profile_id}: {str(e)}",
                operation="FILE_ACCESS",
                table="profiles",
            )

    docx_path_str, filename = await anyio.to_thread.run_sync(
        _get_docx_download_info_sync
    )
    return FileResponse(
        path=docx_path_str,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment"},
    )


@router.get("/{profile_id}/download/md")
async def download_profile_md(
    profile_id: str, current_user: dict = Depends(get_current_user)
):
    """
    @doc Скачать MD файл профиля

    Скачивает профиль в Markdown формате для удобного чтения и печати.
    MD файл содержит человекочитаемое описание профиля с форматированием.

    **Path Parameters:**
    - `profile_id` (str): UUID профиля для скачивания

    **Response:** Файл Markdown для скачивания
    - Content-Type: text/markdown
    - Content-Disposition: attachment
    - Имя файла: profile_{position}_{profile_id_short}.md

    **Authentication:** Требуется Bearer Token

    **File Location Logic:**
    - MD файлы хранятся рядом с JSON в /generated_profiles/{department}/
    - Путь вычисляется детерминистично по profile_id + created_at
    - Имя файла: {position}_{timestamp}.md

    **Markdown Content Structure:**
    - Заголовок с названием должности
    - Общая информация (департамент, подчинение)
    - Обязанности (маркированный список)
    - Квалификация и навыки
    - KPI и метрики (таблица)
    - Метаданные генерации

    **Error Cases:**
    - 404: Профиль не найден в базе данных
    - 404: MD файл не найден в файловой системе
    - 401: Невалидный токен авторизации

    Examples:
        bash>
        # 1. Успешное скачивание MD файла
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/md" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          --output "profile_analyst.md"

        # Response (200 OK): Скачивание файла начнется автоматически
        # Headers:
        # Content-Type: text/markdown
        # Content-Disposition: attachment; filename="profile_Старший_аналитик_данных_4aec3e73.md"
        # Content-Length: 8240

        # File content: Профиль в Markdown с красивым форматированием

        # 2. Просмотр содержимого файла в терминале
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/md" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE" \
          --silent | head -20

        # Output: Первые 20 строк MD файла
        # # Старший аналитик данных
        #
        # ## Общая информация
        # - **Департамент:** Группа анализа данных
        # - **Подчиняется:** Руководитель группы

        # 3. Ошибка - файл не найден (профиль существует, но MD файл удален)
        curl -X GET "http://localhost:8001/api/profiles/4aec3e73-c9bd-4d25-a123-456789abcdef/download/md" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile MD file not found at /generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.md",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "file",
            "resource_id": "/generated_profiles/Группа_анализа_данных/Старший_аналитик_данных_20250110_143022.md"
          }
        }

        # 4. Ошибка - профиль не найден
        curl -X GET "http://localhost:8001/api/profiles/nonexistent-profile-id/download/md" \
          -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Response (404 Not Found):
        {
          "detail": {
            "error": "Profile not found",
            "error_code": "RESOURCE_NOT_FOUND",
            "resource": "profile",
            "resource_id": "nonexistent-profile-id"
          }
        }

        # 5. Комбинированное скачивание обоих форматов
        PROFILE_ID="4aec3e73-c9bd-4d25-a123-456789abcdef"
        AUTH_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTczMTA5Mzc5N30.K8FgXOaVtDyVQs-wc2D8UgPMqGwNb_-pE3YKwN9TjeE"

        # Скачивание JSON
        curl -X GET "http://localhost:8001/api/profiles/${PROFILE_ID}/download/json" \
          -H "Authorization: Bearer ${AUTH_TOKEN}" \
          --output "profile_data.json" --silent

        # Скачивание MD
        curl -X GET "http://localhost:8001/api/profiles/${PROFILE_ID}/download/md" \
          -H "Authorization: Bearer ${AUTH_TOKEN}" \
          --output "profile_readable.md" --silent

        echo "Downloaded both formats:"
        ls -la profile_*
    """
    # Валидация profile_id
    profile_id = validate_profile_id(profile_id)

    def _get_md_download_info_sync() -> tuple[str, str]:
        try:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, department, position, created_at
                FROM profiles
                WHERE id = ?
            """,
                (profile_id,),
            )

            row = cursor.fetchone()
            if not row:
                raise NotFoundError(
                    "Profile not found", resource="profile", resource_id=profile_id
                )

            created_at = datetime.fromisoformat(row["created_at"])
            _, md_path, _ = storage_service.get_profile_paths(
                profile_id=row["id"],
                department=row["department"],
                position=row["position"],
                created_at=created_at,
            )

            if not md_path.exists():
                raise NotFoundError(
                    f"Profile MD file not found at {md_path}",
                    resource="file",
                    resource_id=str(md_path),
                )

            filename = f"profile_{row['position']}_{profile_id[:8]}.md"
            return str(md_path), filename

        except (NotFoundError, ValidationError):
            raise
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Failed to fetch profile {profile_id}: {str(e)}",
                operation="SELECT",
                table="profiles",
            )
        except Exception as e:
            raise DatabaseError(
                f"Unexpected error downloading profile {profile_id}: {str(e)}",
                operation="FILE_ACCESS",
                table="profiles",
            )

    md_path_str, filename = await anyio.to_thread.run_sync(_get_md_download_info_sync)
    return FileResponse(
        path=md_path_str,
        filename=filename,
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment"},
    )
