from django.apps import AppConfig


class OrderRobotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "order_robot"
    verbose_name = "Arolana Order Robot"

    def ready(self):
        from . import signals  # noqa: F401
