"""
@doc Dashboard API - единое API для статистики системы

Оптимизированные endpoint'ы для получения всей статистики dashboard одним запросом.
Минимизирует количество API вызовов и улучшает UX.

Examples:
  python> # GET /api/dashboard/stats - вся статистика одним запросом
  python> # Возвращает: departments, positions, profiles, active_tasks
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List
import logging
import sqlite3
from datetime import datetime

import anyio

from ..models.database import get_db_manager
from ..core.config import config
from ..api.auth import get_current_user

logger = logging.getLogger(__name__)


def get_catalog_service():
    """Получение инициализированного catalog_service"""
    from ..services.catalog_service import catalog_service
    if catalog_service is None:
        raise RuntimeError("CatalogService not initialized. Check main.py lifespan initialization.")
    return catalog_service

# Создаем роутер для dashboard endpoints
dashboard_router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@dashboard_router.get("/stats", response_model=Dict[str, Any])
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """
    @doc
    Получение всей статистики dashboard одним запросом.
    
    Оптимизированный endpoint, который возвращает:
    - Количество департаментов и должностей (из кэша каталога)
    - Количество созданных профилей (из базы)
    - Список активных задач генерации
    - Процент покрытия должностей профилями
    
    ### Пример запроса:
    ```bash
    curl -X GET "http://localhost:8001/api/dashboard/stats" \
      -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    ```
    
    ### Пример успешного ответа:
    ```json
    {
      "success": true,
      "message": "Dashboard статистика получена",
      "data": {
        "summary": {
          "departments_count": 510,
          "positions_count": 1487,
          "profiles_count": 8,
          "completion_percentage": 0.5,
          "active_tasks_count": 0
        },
        "departments": {
          "total": 510,
          "with_positions": 488,
          "average_positions": 2.9
        },
        "positions": {
          "total": 1487,
          "with_profiles": 8,
          "without_profiles": 1479,
          "coverage_percent": 0.5
        },
        "profiles": {
          "total": 8,
          "percentage_complete": 0.5
        },
        "active_tasks": [],
        "metadata": {
          "last_updated": "2025-09-10T03:17:54.377302",
          "data_sources": {
            "catalog": "cached",
            "profiles": "database",
            "tasks": "memory"
          }
        }
      }
    }
    ```
    
    ### 📊 Описание данных:
    - **summary**: Основные метрики для карточек dashboard
    - **departments**: Детальная статистика по департаментам
    - **positions**: Статистика покрытия должностей профилями
    - **profiles**: Информация о созданных профилях
    - **active_tasks**: Список текущих задач генерации (TODO: интеграция с generation manager)
    - **metadata**: Метаданные о источниках данных и времени обновления
    
    Returns:
        Dict с полной статистикой для dashboard
        
    Examples:
        python> response = await get_dashboard_stats()
        python> # {'success': True, 'data': {'summary': {'departments_count': 510, 'positions_count': 1487}}}
    """
    try:
        logger.info(f"Getting dashboard stats for user {current_user['username']}")

        # 1. Получаем статистику каталога (кэшированная, быстро)
        catalog_service = get_catalog_service()
        departments = catalog_service.get_departments()

        # Считаем общее количество должностей
        total_positions = 0
        for dept in departments:
            positions = catalog_service.get_positions(dept["name"])
            total_positions += len(positions)

        # 2. Получаем количество профилей (одним SQL запросом)
        def _count_profiles_sync() -> int:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM profiles")
            result = cursor.fetchone()
            return int(result[0]) if result else 0

        profiles_count = await anyio.to_thread.run_sync(_count_profiles_sync)

        # 3. Получаем активные задачи (заглушка - TODO: реализовать когда будет готов generation manager)
        active_tasks = []
        # TODO: Интеграция с generation manager когда будет готов
        # try:
        #     all_tasks = generation_manager.get_all_tasks()
        #     ...
        # except Exception as e:
        #     logger.warning(f"Could not get active tasks: {e}")
        #     active_tasks = []

        # 4. Вычисляем метрики
        completion_percentage = (
            (profiles_count / total_positions * 100) if total_positions > 0 else 0
        )
        departments_with_profiles = len(
            set([dept["name"] for dept in departments if dept["positions_count"] > 0])
        )

        # 5. Формируем ответ
        response = {
            "success": True,
            "message": "Dashboard статистика получена",
            "data": {
                # Основные метрики
                "summary": {
                    "departments_count": len(departments),
                    "positions_count": total_positions,
                    "profiles_count": profiles_count,
                    "completion_percentage": round(completion_percentage, 1),
                    "active_tasks_count": len(active_tasks),
                },
                # Детальная статистика
                "departments": {
                    "total": len(departments),
                    "with_positions": departments_with_profiles,
                    "average_positions": (
                        round(total_positions / len(departments), 1)
                        if departments
                        else 0
                    ),
                },
                "positions": {
                    "total": total_positions,
                    "with_profiles": profiles_count,
                    "without_profiles": total_positions - profiles_count,
                    "coverage_percent": round(completion_percentage, 1),
                },
                "profiles": {
                    "total": profiles_count,
                    "percentage_complete": round(completion_percentage, 1),
                },
                # Активные задачи (последние 5)
                "active_tasks": active_tasks,
                # Метаданные
                "metadata": {
                    "last_updated": datetime.now().isoformat(),
                    "data_sources": {
                        "catalog": "cached",
                        "profiles": "database",
                        "tasks": "memory",
                    },
                },
            },
        }

        logger.info(
            f"Dashboard stats: {len(departments)} depts, {total_positions} positions, {profiles_count} profiles, {len(active_tasks)} active tasks"
        )
        return response

    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статистики dashboard: {str(e)}",
        )


@dashboard_router.get("/stats/minimal", response_model=Dict[str, Any])
async def get_minimal_stats(current_user: dict = Depends(get_current_user)):
    """
    @doc
    Получение минимальной статистики для компактных компонентов.
    
    Возвращает только самые важные метрики:
    - Общее количество должностей
    - Количество созданных профилей  
    - Процент завершенности
    - Количество активных задач
    
    Максимально быстрый запрос для UX критичных компонентов.
    
    ### Пример запроса:
    ```bash
    curl -X GET "http://localhost:8001/api/dashboard/stats/minimal" \
      -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    ```
    
    ### Пример успешного ответа:
    ```json
    {
      "success": true,
      "data": {
        "positions_count": 1487,
        "profiles_count": 8,
        "completion_percentage": 0.5,
        "active_tasks_count": 0,
        "last_updated": "2025-09-10T03:18:00.094062"
      }
    }
    ```
    
    ### ⚡ Оптимизация производительности:
    - Минимальное количество данных для быстрой загрузки
    - Использует кэшированные данные каталога
    - Один SQL запрос для подсчета профилей
    - Идеально для компонентов реального времени
    
    ### 🎯 Использование в UI:
    - Компактные виджеты dashboard
    - Индикаторы прогресса
    - Уведомления о статусе системы
    - Мобильные представления
    
    Returns:
        Dict с минимальной статистикой
        
    Examples:
        python> response = await get_minimal_stats()
        python> # {'success': True, 'data': {'positions_count': 1487, 'profiles_count': 8, 'completion_percentage': 0.5}}
    """
    try:
        logger.info(f"Getting minimal stats for user {current_user['username']}")

        # Используем кэшированные данные каталога
        catalog_service = get_catalog_service()
        departments = catalog_service.get_departments()
        total_positions = sum(dept["positions_count"] for dept in departments)

        # Быстрый подсчет профилей
        def _count_profiles_sync() -> int:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM profiles")
            result = cursor.fetchone()
            return int(result[0]) if result else 0

        profiles_count = await anyio.to_thread.run_sync(_count_profiles_sync)

        # Подсчет активных задач (заглушка)
        active_tasks_count = 0
        # TODO: Интеграция с generation manager
        # try:
        #     all_tasks = generation_manager.get_all_tasks()
        #     active_tasks_count = len([...])
        # except:
        #     active_tasks_count = 0

        completion_percentage = (
            (profiles_count / total_positions * 100) if total_positions > 0 else 0
        )

        response = {
            "success": True,
            "data": {
                "positions_count": total_positions,
                "profiles_count": profiles_count,
                "completion_percentage": round(completion_percentage, 1),
                "active_tasks_count": active_tasks_count,
                "last_updated": datetime.now().isoformat(),
            },
        }

        logger.info(
            f"Minimal stats: {total_positions} positions, {profiles_count} profiles, {completion_percentage:.1f}% complete"
        )
        return response

    except Exception as e:
        logger.error(f"Error getting minimal stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения минимальной статистики: {str(e)}",
        )


@dashboard_router.get("/stats/activity", response_model=Dict[str, Any])
async def get_activity_stats(current_user: dict = Depends(get_current_user)):
    """
    @doc
    Получение статистики активности для ленты dashboard.
    
    Возвращает:
    - Активные задачи генерации с прогрессом
    - Недавно созданные профили (последние 10)
    - Статистику активности за период
    
    ### Пример запроса:
    ```bash
    curl -X GET "http://localhost:8001/api/dashboard/stats/activity" \
      -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    ```
    
    ### Пример успешного ответа:
    ```json
    {
      "success": true,
      "data": {
        "active_tasks": [],
        "recent_profiles": [
          {
            "department": "Департамент по связям с общественностью",
            "position": "Специалист по связям с общественностью",
            "employee_name": null,
            "created_at": "2025-09-09T18:47:26.337714",
            "status": "completed",
            "created_by": "admin"
          },
          {
            "department": "Группа анализа данных",
            "position": "Исправленный аналитик v2",
            "employee_name": "Иванов Иван Иванович",
            "created_at": "2025-09-09T18:18:52.529865",
            "status": "completed",
            "created_by": "admin"
          }
        ],
        "summary": {
          "active_tasks_count": 0,
          "recent_profiles_count": 8,
          "has_activity": true
        },
        "last_updated": "2025-09-10T03:18:05.749119"
      }
    }
    ```
    
    ### 📈 Структура данных активности:
    - **active_tasks**: Список выполняющихся задач генерации (TODO: интеграция с generation manager)
    - **recent_profiles**: Последние 10 созданных профилей с метаданными
    - **summary**: Агрегированная статистика активности
    - **has_activity**: Флаг наличия активности для условного рендеринга
    
    ### 🔄 Обновления в реальном времени:
    - Endpoint оптимизирован для частых вызовов
    - Данные сортируются по времени создания (DESC)
    - Включает информацию о создателе профиля
    - Поддерживает пустые значения employee_name
    
    Returns:
        Dict со статистикой активности
        
    Examples:
        python> response = await get_activity_stats()
        python> # {'success': True, 'data': {'recent_profiles': [...], 'has_activity': True}}
    """
    try:
        logger.info(f"Getting activity stats for user {current_user['username']}")

        # 1. Активные задачи (заглушка)
        active_tasks = []
        # TODO: Интеграция с generation manager
        # try:
        #     all_tasks = generation_manager.get_all_tasks()
        #     active_tasks = [...]
        # except:
        #     active_tasks = []

        # 2. Недавние профили (последние 10)
        def _get_recent_profiles_sync() -> list[dict[str, Any]]:
            conn = get_db_manager().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.department, p.position, p.employee_name, p.created_at, p.status,
                       u.username as created_by
                FROM profiles p
                LEFT JOIN users u ON p.created_by = u.id
                ORDER BY p.created_at DESC
                LIMIT 10
            """
            )

            recent = []
            for row in cursor.fetchall():
                recent.append(
                    {
                        "department": row["department"],
                        "position": row["position"],
                        "employee_name": row["employee_name"],
                        "created_at": row["created_at"],
                        "status": row["status"],
                        "created_by": row["created_by"],
                    }
                )
            return recent

        recent_profiles = await anyio.to_thread.run_sync(_get_recent_profiles_sync)

        response = {
            "success": True,
            "data": {
                "active_tasks": active_tasks,
                "recent_profiles": recent_profiles,
                "summary": {
                    "active_tasks_count": len(active_tasks),
                    "recent_profiles_count": len(recent_profiles),
                    "has_activity": len(active_tasks) > 0 or len(recent_profiles) > 0,
                },
                "last_updated": datetime.now().isoformat(),
            },
        }

        logger.info(
            f"Activity stats: {len(active_tasks)} active tasks, {len(recent_profiles)} recent profiles"
        )
        return response

    except Exception as e:
        logger.error(f"Error getting activity stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статистики активности: {str(e)}",
        )


if __name__ == "__main__":
    print("✅ Dashboard API endpoints created!")
    print("📍 Available endpoints:")
    print("  - GET /api/dashboard/stats - Full dashboard statistics")
    print("  - GET /api/dashboard/stats/minimal - Essential metrics only")
    print("  - GET /api/dashboard/stats/activity - Activity feed data")
