from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "agni.documents"
    label = "documents"

    def ready(self) -> None:
        # Registers the `document.scan` job handler with the platform worker.
        from . import scanning  # noqa: F401
