import sys

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from accounts.models import User
from orders.models import Order
from products.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductVariant,
    VendorProductOffer,
)


class Command(BaseCommand):
    help = "Safely report marketplace catalog database counts and migration status."

    def handle(self, *args, **options):
        try:
            counts = {
                "Product": Product.objects.count(),
                "Category": Category.objects.count(),
                "Brand": Brand.objects.count(),
                "ProductVariant": ProductVariant.objects.count(),
                "VendorProductOffer": VendorProductOffer.objects.count(),
                "ProductImage": ProductImage.objects.count(),
                "Order": Order.objects.count(),
                "User": User.objects.count(),
            }
            settings_dict = connection.settings_dict
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            applied = MigrationRecorder(connection).applied_migrations()
            product_table = Product._meta.db_table
            usable_catalog = (
                counts["Product"] > 0
                and Product.objects.filter(is_active=True, approval_status="approved").exists()
            )

            self.stdout.write(f"database_engine={settings_dict.get('ENGINE', '')}")
            self.stdout.write(f"database_host={settings_dict.get('HOST', '') or 'local/default'}")
            self.stdout.write(f"database_name={settings_dict.get('NAME', '')}")
            self.stdout.write(f"product_table={product_table}")
            for label, count in counts.items():
                self.stdout.write(f"{label}={count}")
            self.stdout.write(f"installed_apps={len(apps.get_app_configs())}")
            self.stdout.write(f"migrations_applied={len(applied)}")
            self.stdout.write(f"migrations_pending={len(plan)}")
            self.stdout.write(
                "catalog_status=usable"
                if usable_catalog
                else "catalog_status=empty_or_no_active_approved_products"
            )
            sys.exit(0 if usable_catalog else 1)
        except SystemExit:
            raise
        except Exception as exc:
            self.stderr.write(f"catalog_diagnostic_failed={exc.__class__.__name__}")
            sys.exit(2)
