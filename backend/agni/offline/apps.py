from django.apps import AppConfig


class OfflineConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "agni.offline"
    label = "offline"
