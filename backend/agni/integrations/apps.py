from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "agni.integrations"
    label = "integrations"
