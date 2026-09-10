from django.apps import AppConfig


class PlatformConfig(AppConfig):
    name = "agni.platform"
    label = "platform"
    verbose_name = "Agni Setu platform kernel"
    default_auto_field = "django.db.models.BigAutoField"
