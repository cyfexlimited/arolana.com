from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products"

    def ready(self):
        # Importing the module connects the @receiver-decorated handlers.
        from . import signals  # noqa: F401
