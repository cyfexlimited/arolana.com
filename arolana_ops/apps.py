from django.apps import AppConfig


class ArolanaOpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "arolana_ops"
    verbose_name = "Arolana Ops"

    def ready(self):
        import arolana_ops.signals  # noqa: F401

