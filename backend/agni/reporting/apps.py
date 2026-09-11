from django.apps import AppConfig


class ReportingConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "agni.reporting"
    label = "reporting"
