from django.apps import AppConfig


class PoliciesConfig(AppConfig):
    name = "agni.policies"
    label = "policies"
    verbose_name = "Agni Setu service policy"
    default_auto_field = "django.db.models.BigAutoField"
