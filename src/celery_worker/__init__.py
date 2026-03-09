"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: Celery worker application factory
"""

from celery import Celery


def create_celery_app():
    """
    Input: None
    Output: Celery application instance
    Details: Initializes Celery with Redis broker and task discovery
    """
    app = Celery('shse')
    app.config_from_object('src.celery_worker.config:CeleryConfig')
    app.autodiscover_tasks(['src.celery_worker.tasks'])
    return app


celery_app = create_celery_app()
